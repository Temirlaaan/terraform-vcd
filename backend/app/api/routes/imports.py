"""Import existing VCD edge gateways as managed deployments.

Workflow:
  1. Operator picks an org/vdc/edge from a cascading dropdown.
  2. ``POST /deployments/import`` creates a Deployment row (kind='imported'),
     spins a temporary Terraform workspace pointed at the per-deployment
     S3 state key, and walks the edge with ``drift_importer.import_unmanaged``
     to pull every supported NSX-T sub-resource into state + HCL.
  3. The resulting ``main.tf`` is persisted as ``deployment.hcl`` and a
     v1 snapshot is taken with ``label='imported_baseline'`` (pinned).

After import the deployment behaves exactly like a manual or migrated
deployment: editor opens, plan/apply cycle works, drift sync covers it.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.core import minio_client
from app.core.deployment_builder import build_hcl, summary_from_spec
from app.core.deployment_spec_from_state import parse_state_text
from app.core.drift_importer import import_unmanaged
from app.core.import_firewall import import_firewall_for_edge
from app.core.tf_runner import TerraformRunner
from app.core.tf_workspace import TerraformWorkspace
from app.core.version_store import snapshot_version
from app.database import get_db
from app.integrations.vcd_client import vcd_client
from app.models.deployment import Deployment
from app.schemas.deployment import DeploymentOut
from app.schemas.deployment_spec import DeploymentSpec, TargetSpec
from app.schemas.terraform import _validate_safe_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["deployments-import"])

_READ_ROLE = require_roles("tf-admin", "tf-operator", "tf-viewer")
_WRITE_ROLE = require_roles("tf-admin", "tf-operator")


# ----------------------------------------------------------------------
# Available edges (for the picker)
# ----------------------------------------------------------------------


@router.get("/available-edges")
async def list_available_edges(
    vdc_id: str | None = Query(default=None, description="VDC URN to filter by"),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_READ_ROLE),  # noqa: ARG001
) -> dict:
    """List edges from VCD with a ``deployed`` flag per edge.

    Filtering by ``vdc_id`` (URN) is required in practice — VCD CloudAPI
    rejects FIQL filters on ``orgRef.name`` / ``orgVdc.name`` with HTTP
    400, so we route through the URN-based ``edgeGateways?filter=
    (orgVdc.id==<urn>)`` endpoint.

    The frontend uses this for the import picker — already-managed edges
    are shown disabled with the existing deployment id surfaced so the
    operator can navigate to it instead of double-importing.
    """
    try:
        if vdc_id:
            edges = await vcd_client.get_edge_gateways_by_vdc_id(vdc_id=vdc_id)
            for e in edges:
                e.setdefault("vdc_name", None)
                e.setdefault("gateway_type", None)
        else:
            edges = await vcd_client.get_edge_gateways()
    except Exception as exc:
        logger.error("VCD API error in available-edges: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="VCD API is unavailable. Try again later.",
        )

    if not edges:
        return {"items": [], "count": 0}

    edge_ids = [e["id"] for e in edges if e.get("id")]
    deployed_map: dict[str, tuple[uuid.UUID, str]] = {}
    if edge_ids:
        rows = await db.execute(
            select(
                Deployment.target_edge_id,
                Deployment.id,
                Deployment.kind,
            ).where(Deployment.target_edge_id.in_(edge_ids))
        )
        for edge_id, dep_id, kind in rows.all():
            deployed_map[edge_id] = (dep_id, kind)

    items = []
    for e in edges:
        dep = deployed_map.get(e.get("id"))
        items.append(
            {
                "id": e.get("id"),
                "name": e.get("name"),
                "vdc_name": e.get("vdc_name"),
                "gateway_type": e.get("gateway_type"),
                "deployed": dep is not None,
                "deployment_id": str(dep[0]) if dep else None,
                "deployment_kind": dep[1] if dep else None,
            }
        )
    return {"items": items, "count": len(items)}


# ----------------------------------------------------------------------
# Import endpoint
# ----------------------------------------------------------------------


class DeploymentImportRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    target_org: str = Field(..., min_length=1, max_length=255)
    target_vdc: str = Field(..., min_length=1, max_length=255)
    target_vdc_id: str = Field(..., min_length=1, max_length=255)
    target_edge_id: str = Field(..., min_length=1, max_length=255)
    target_edge_name: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_safe_name(v, "name")


def _spec_key(deployment_id: uuid.UUID) -> str:
    return f"deployments/{deployment_id}/current/spec.json"


def _provider_tf_for_deployment(deployment_id: uuid.UUID) -> str:
    """Render provider+backend HCL for the deployment-scoped workspace."""
    # Re-use migration's renderer — same template, same state key scheme.
    from app.api.routes.migration import _render_provider_tf

    return _render_provider_tf(deployment_id)


@router.post(
    "/import",
    response_model=DeploymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_existing_edge(
    body: DeploymentImportRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLE),
) -> DeploymentOut:
    """Create an ``imported`` deployment from an existing VCD edge.

    Steps:
      * 409 if this edge is already tracked by any deployment
      * Insert Deployment row (so MinIO state key is stable)
      * Render variables-only seed HCL + provider.tf in a workspace
      * ``terraform init`` (creates empty state in MinIO)
      * Walk VCD via ``import_unmanaged`` — appends resource HCL +
        ``terraform import`` per resource
      * Persist final main.tf as ``deployment.hcl`` + spec.json
      * Snapshot v1 (``imported_baseline``, pinned)
    """
    # Pre-check: target_edge_id must not already be managed.
    existing = await db.execute(
        select(Deployment.id, Deployment.kind).where(
            Deployment.target_edge_id == body.target_edge_id
        )
    )
    row = existing.first()
    if row is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Edge {body.target_edge_id} already managed by deployment "
                f"{row[0]} (kind={row[1]})."
            ),
        )

    edge_label = body.target_edge_name or body.target_edge_id
    name = (body.name or f"imported_{edge_label}").strip()
    description = body.description or (
        f"Imported -> {body.target_org}/{body.target_vdc}/{edge_label}"
    )

    target = TargetSpec(
        org=body.target_org,
        vdc=body.target_vdc,
        vdc_id=body.target_vdc_id,
        edge_id=body.target_edge_id,
        edge_name=body.target_edge_name,
    )
    seed_spec = DeploymentSpec(target=target)
    seed_hcl = build_hcl(seed_spec)

    deployment = Deployment(
        name=name,
        kind="imported",
        description=description,
        source_host="(imported)",
        source_edge_uuid=body.target_edge_id,
        source_edge_name=body.target_edge_name or body.target_edge_id,
        verify_ssl=False,
        target_org=body.target_org,
        target_vdc=body.target_vdc,
        target_vdc_id=body.target_vdc_id,
        target_edge_id=body.target_edge_id,
        target_edge_name=body.target_edge_name,
        hcl=seed_hcl,
        summary={"ip_sets": 0, "app_port_profiles": 0,
                 "firewall": 0, "nat": 0, "static_routes": 0},
        created_by=user.username,
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)

    operation_id = uuid.uuid4()
    workspace = TerraformWorkspace(body.target_org, operation_id)
    workspace.work_dir.mkdir(parents=True, exist_ok=True)
    main_tf = workspace.work_dir / "main.tf"
    main_tf.write_text(seed_hcl, encoding="utf-8")
    (workspace.work_dir / "provider.tf").write_text(
        _provider_tf_for_deployment(deployment.id), encoding="utf-8"
    )

    runner = TerraformRunner(workspace.work_dir, operation_id=None)

    try:
        init_result = await runner.init()
        if not init_result.success:
            raise HTTPException(
                status_code=500,
                detail=f"terraform init failed: {init_result.stderr[:500]}",
            )

        # Empty state for fresh import — drift_importer handles missing
        # state by treating everything in VCD as unmanaged.
        empty_state: dict = {"resources": []}

        summary = await import_unmanaged(
            runner,
            workspace.work_dir,
            target_org=body.target_org,
            target_vdc=body.target_vdc,
            target_vdc_id=body.target_vdc_id,
            target_edge_id=body.target_edge_id,
            target_edge_name=body.target_edge_name,
            state_json=empty_state,
        )

        # Firewall is a single resource per edge (not per-rule), so it
        # lives outside the standard import_unmanaged loop. Run after
        # ip_sets / app_port_profiles are in state so the firewall block
        # can reference their URNs.
        try:
            # Refresh state_json after the previous imports so the
            # firewall importer sees what's already managed.
            state_key = f"deployments/{deployment.id}/current/terraform.tfstate"
            current_state: dict = {"resources": []}
            if await minio_client.exists(state_key):
                state_text = await minio_client.get_text(state_key)
                current_state = json.loads(state_text)
            fw_summary = await import_firewall_for_edge(
                runner,
                workspace.work_dir,
                target_org=body.target_org,
                target_vdc=body.target_vdc,
                target_edge_id=body.target_edge_id,
                target_edge_name=body.target_edge_name,
                state_json=current_state,
            )
            summary.setdefault("imported", []).extend(fw_summary.get("imported", []))
            summary.setdefault("skipped", []).extend(fw_summary.get("skipped", []))
        except Exception:
            logger.exception(
                "import: firewall import failed deployment=%s", deployment.id
            )

        final_hcl = main_tf.read_text(encoding="utf-8")

        deployment.hcl = final_hcl
        # Re-derive summary from spec parsed back from the new state.
        try:
            state_key = f"deployments/{deployment.id}/current/terraform.tfstate"
            if await minio_client.exists(state_key):
                state_text = await minio_client.get_text(state_key)
                spec = parse_state_text(state_text, target)
                deployment.summary = summary_from_spec(spec)
                await minio_client.put_text(
                    _spec_key(deployment.id),
                    json.dumps(spec.model_dump(), ensure_ascii=False),
                    content_type="application/json",
                )
            else:
                # No state yet — empty edge, keep zero summary.
                logger.info(
                    "import: no state file produced for %s (empty edge)",
                    deployment.id,
                )
        except Exception:
            logger.exception(
                "import: spec rebuild failed deployment=%s", deployment.id
            )

        deployment.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(deployment)

        # Snapshot v1 baseline (pinned). Imported edges that have zero
        # NSX-T sub-resources still get a v1 — initial_baseline auto-pin
        # in version_store does the right thing.
        try:
            ver = await snapshot_version(
                db,
                deployment.id,
                workspace.work_dir,
                source="import",
                created_by=user.username,
                label="imported_baseline",
                is_pinned=True,
            )
            if ver is not None:
                logger.info(
                    "import: snapshot v%d pinned for deployment=%s",
                    ver.version_num, deployment.id,
                )
        except Exception:
            logger.exception(
                "import: snapshot failed deployment=%s", deployment.id
            )

        logger.info(
            "user=%s action=deployment_import id=%s edge=%s imported=%d skipped=%d",
            user.username,
            deployment.id,
            body.target_edge_id,
            len(summary.get("imported", [])),
            len(summary.get("skipped", [])),
        )
        return DeploymentOut.model_validate(deployment)
    finally:
        try:
            workspace.cleanup()
        except Exception:
            logger.warning("import: workspace cleanup failed (non-fatal)")
