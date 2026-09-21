"""Carry IPsec VPN tunnels from a legacy NSX-V edge onto an NSX-T one.

A tab of its own rather than part of the firewall/NAT migration, because
the two behave differently: firewall rules are idempotent and can be
applied and verified afterwards, while a tunnel is a live session with a
third party that has to be switched over one at a time.

Pre-shared keys never travel through the browser. The preview returns
tunnels with the keys stripped, and plan re-reads them server-side from
the source VCD using the same short-lived handle, so what is applied and
what was read come from one fetch rather than a round trip.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.config import settings
from app.core import vcd_handle
from app.core.aria_attribution import Attribution, retag_hcl
from app.core.ipsec_psk import psk_vars_from_tunnels
from app.core.locking import (
    acquire_org_lock,
    get_org_lock_holder,
    release_org_lock,
)
from app.core.tf_runner import TerraformRunner
from app.core.tf_workspace import TerraformWorkspace
from app.database import get_db
from app.migration.fetcher import LegacyVcdFetcher
from app.migration.generator import MigrationHCLGenerator, _prepare_ipsec
from app.migration.normalizer import normalize_edge_snapshot
from app.models.operation import Operation, OperationStatus, OperationType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ipsec-migration", tags=["ipsec-migration"])

_WRITE_ROLES = require_roles("tf-admin", "tf-operator")


# ---------------------------------------------------------------------------
#  Schemas
# ---------------------------------------------------------------------------

class SourceTarget(BaseModel):
    """Where tunnels come from and where they are going."""

    host: str | None = Field(None, description="Legacy VCD URL, when api_token is used")
    api_token: str | None = Field(None, description="Prefer handle over this")
    handle: str | None = Field(None, description="Opaque handle from /migration/auth-handle")
    source_edge_uuid: str = Field(..., min_length=1)
    verify_ssl: bool = False

    target_org: str = Field(..., min_length=1)
    target_vdc: str = Field(..., min_length=1)
    target_vdc_id: str = Field(..., min_length=1)
    target_edge_id: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_auth(self) -> "SourceTarget":
        if not self.handle and not self.api_token:
            raise ValueError("Either 'handle' or 'api_token' must be supplied")
        if self.api_token and not self.host:
            raise ValueError("'host' is required when using 'api_token'")
        return self


class TunnelOut(BaseModel):
    """One tunnel, with the pre-shared key deliberately absent."""

    name: str
    slug: str | None = None
    enabled_on_source: bool
    local_ip: str
    peer_ip: str
    remote_id: str | None
    local_networks: list[str]
    remote_networks: list[str]
    encryption: str | None
    digest: str | None
    dh_group: str | None
    ike_version: str | None
    pfs: bool
    psk_readable: bool
    migratable: bool
    unsupported: list[str]


class PreviewOut(BaseModel):
    hcl: str
    tunnels: list[TunnelOut]
    total: int
    migratable: int
    skipped: int
    warnings: list[str]


class ApplyIn(BaseModel):
    target_org: str = Field(..., min_length=1)
    plan_operation_id: uuid.UUID


class OperationStarted(BaseModel):
    operation_id: uuid.UUID


# ---------------------------------------------------------------------------
#  Shared pipeline
# ---------------------------------------------------------------------------

async def _resolve_auth(body: SourceTarget) -> tuple[str, str]:
    if body.handle:
        payload = await vcd_handle.resolve(body.handle)
        if payload is None:
            raise HTTPException(
                status_code=401,
                detail="VCD auth handle expired or unknown — re-enter credentials.",
            )
        return payload.host, payload.api_token
    return body.host or "", body.api_token or ""


async def _read_and_generate(body: SourceTarget) -> tuple[str, list[dict], list[dict]]:
    """Fetch the source edge and render IPsec HCL.

    Returns (hcl, renderable tunnels with slugs and keys, skipped tunnels).
    Callers that send anything to the browser must strip the keys first.
    """
    host, token = await _resolve_auth(body)
    fetcher = LegacyVcdFetcher(host=host, api_token=token, verify_ssl=body.verify_ssl)

    try:
        raw = await fetcher.fetch_edge_snapshot(body.source_edge_uuid)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            raise HTTPException(status_code=401, detail="Legacy VCD rejected the token.")
        raise HTTPException(
            status_code=502,
            detail=f"Legacy VCD returned HTTP {status} for edge {body.source_edge_uuid}.",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach legacy VCD: {exc}")

    if "ipsec_config.xml" not in raw:
        raise HTTPException(
            status_code=404,
            detail=(
                "No IPsec configuration on this edge. If you expected tunnels, "
                "the token may lack rights on the NSX-V proxy."
            ),
        )

    normalized = normalize_edge_snapshot(raw)
    renderable, skipped = _prepare_ipsec(normalized.get("ipsec", {}))

    # Render only the IPsec section: firewall and NAT have their own tab.
    tpl_dir = Path(__file__).resolve().parents[3] / "templates" / "migration"
    jenv = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jenv.filters["hcl_escape"] = MigrationHCLGenerator()._env.filters["hcl_escape"]

    ctx = {
        "ipsec_tunnels": renderable,
        "ipsec_skipped": skipped,
        "target_org_name": body.target_org,
        "target_vdc_name": body.target_vdc,
        "target_vdc_id": body.target_vdc_id,
        "target_edge_id": body.target_edge_id,
    }
    hcl = (
        jenv.get_template("variables.tf.j2").render(**ctx)
        + "\n"
        + jenv.get_template("ipsec.tf.j2").render(**ctx)
    )
    return hcl, renderable, skipped


def _to_out(tunnel: dict) -> TunnelOut:
    return TunnelOut(
        name=tunnel.get("name", ""),
        slug=tunnel.get("slug"),
        enabled_on_source=bool(tunnel.get("enabled")),
        local_ip=tunnel.get("local_ip", ""),
        peer_ip=tunnel.get("peer_ip", ""),
        remote_id=tunnel.get("remote_id"),
        local_networks=tunnel.get("local_networks", []),
        remote_networks=tunnel.get("remote_networks", []),
        encryption=tunnel.get("encryption"),
        digest=tunnel.get("digest"),
        dh_group=tunnel.get("dh_group"),
        ike_version=tunnel.get("ike_version"),
        pfs=bool(tunnel.get("pfs")),
        # Whether a key was readable, never the key itself.
        psk_readable=bool(tunnel.get("psk")),
        migratable=bool(tunnel.get("migratable")),
        unsupported=tunnel.get("unsupported", []),
    )


def _warnings(renderable: list[dict], skipped: list[dict]) -> list[str]:
    out: list[str] = []
    if skipped:
        out.append(
            f"{len(skipped)} tunnel(s) cannot be migrated as they are and are "
            "left on the source edge — see the reasons below."
        )
    no_key = [t["name"] for t in renderable if not t.get("psk")]
    if no_key:
        out.append(
            "No pre-shared key was returned for: "
            + ", ".join(no_key)
            + ". Terraform will refuse to plan without one."
        )
    if renderable:
        out.append(
            f"All {len(renderable)} tunnel(s) are created disabled. Enable them "
            "one at a time during cutover, after the source side is down."
        )
    return out


# ---------------------------------------------------------------------------
#  Endpoints
# ---------------------------------------------------------------------------

@router.post("/preview", response_model=PreviewOut)
async def preview(
    body: SourceTarget,
    user: AuthenticatedUser = Depends(_WRITE_ROLES),
) -> PreviewOut:
    """Read the source edge and show what would be created."""
    logger.info(
        "user=%s action=ipsec_preview src_edge=%s dst_edge=%s",
        user.username, body.source_edge_uuid, body.target_edge_id,
    )
    hcl, renderable, skipped = await _read_and_generate(body)
    return PreviewOut(
        hcl=hcl,
        tunnels=[_to_out(t) for t in renderable] + [_to_out(t) for t in skipped],
        total=len(renderable) + len(skipped),
        migratable=len(renderable),
        skipped=len(skipped),
        warnings=_warnings(renderable, skipped),
    )


@router.post("/plan", response_model=OperationStarted)
async def plan(
    body: SourceTarget,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLES),
) -> OperationStarted:
    """Regenerate server-side and run init + plan.

    The source is read again rather than trusting HCL posted back by the
    browser: that keeps the pre-shared keys out of the round trip, and
    guarantees the keys and the variable names they fill come from the
    same fetch.
    """
    operation_id = uuid.uuid4()
    lock_name = f"ipsec-{body.target_org}"

    logger.info(
        "user=%s action=ipsec_plan src_edge=%s dst_edge=%s operation_id=%s",
        user.username, body.source_edge_uuid, body.target_edge_id, operation_id,
    )

    hcl, renderable, _ = await _read_and_generate(body)
    if not renderable:
        raise HTTPException(
            status_code=400,
            detail="Nothing to plan — no tunnel on this edge can be migrated as-is.",
        )

    if not await acquire_org_lock(lock_name, str(operation_id)):
        holder = await get_org_lock_holder(lock_name)
        raise HTTPException(
            status_code=409,
            detail=f"IPsec work on '{body.target_org}' is locked by operation {holder}.",
        )

    db.add(Operation(
        id=operation_id,
        type=OperationType.PLAN,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=body.target_org,
        target_edge_id=body.target_edge_id,
    ))
    await db.commit()

    try:
        workspace = _write_workspace(
            lock_name, operation_id, body.target_edge_id, hcl, user.username
        )
    except Exception as exc:
        logger.exception("ipsec workspace failed for %s", operation_id)
        await _fail(db, operation_id, str(exc), lock_name)
        raise HTTPException(status_code=500, detail=f"Could not create workspace: {exc}")

    psk_vars = psk_vars_from_tunnels(renderable)
    asyncio.create_task(_run_plan(operation_id, lock_name, workspace, psk_vars))
    return OperationStarted(operation_id=operation_id)


@router.post("/apply", response_model=OperationStarted)
async def apply(
    body: ApplyIn,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLES),
) -> OperationStarted:
    """Apply the reviewed plan.

    No keys are needed here: plan.bin already carries the resolved values,
    so nothing has to be read from the source again.
    """
    lock_name = f"ipsec-{body.target_org}"
    workspace = TerraformWorkspace(lock_name, body.plan_operation_id)
    if not (workspace.work_dir / "plan.bin").exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "That plan's workspace is gone — plans do not survive a backend "
                "restart. Run the plan again."
            ),
        )

    operation_id = uuid.uuid4()
    logger.info(
        "user=%s action=ipsec_apply plan_op=%s operation_id=%s",
        user.username, body.plan_operation_id, operation_id,
    )

    if not await acquire_org_lock(lock_name, str(operation_id)):
        holder = await get_org_lock_holder(lock_name)
        raise HTTPException(
            status_code=409,
            detail=f"IPsec work on '{body.target_org}' is locked by operation {holder}.",
        )

    db.add(Operation(
        id=operation_id,
        type=OperationType.APPLY,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=body.target_org,
    ))
    await db.commit()

    asyncio.create_task(_run_apply(operation_id, lock_name, workspace))
    return OperationStarted(operation_id=operation_id)


# ---------------------------------------------------------------------------
#  Terraform plumbing
# ---------------------------------------------------------------------------

def _state_key(edge_id: str) -> str:
    edge_slug = edge_id.rsplit(":", 1)[-1] or "edge"
    return f"ipsec-migration/{edge_slug}/terraform.tfstate"


def _write_workspace(
    lock_name: str,
    operation_id: uuid.UUID,
    edge_id: str,
    hcl: str,
    username: str,
) -> TerraformWorkspace:
    workspace = TerraformWorkspace(lock_name, operation_id)
    workspace.work_dir.mkdir(parents=True, exist_ok=True)

    tagged = retag_hcl(
        hcl, Attribution(kc_username=username or "unknown", op_id=str(operation_id))
    )
    (workspace.work_dir / "main.tf").write_text(tagged, encoding="utf-8")

    tpl_dir = Path(__file__).resolve().parents[3] / "templates" / "migration"
    jenv = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    (workspace.work_dir / "provider.tf").write_text(
        jenv.get_template("provider.tf.j2").render(state_key=_state_key(edge_id)),
        encoding="utf-8",
    )
    return workspace


async def _fail(db: AsyncSession, operation_id: uuid.UUID, message: str, lock: str) -> None:
    op = await db.get(Operation, operation_id)
    if op is not None:
        op.status = OperationStatus.FAILED
        op.error_message = message
        op.completed_at = datetime.now(timezone.utc)
        await db.commit()
    await release_org_lock(lock, str(operation_id))


async def _finish(operation_id: uuid.UUID, lock: str, result) -> None:
    from app.database import async_session

    try:
        async with async_session() as db:
            op = await db.get(Operation, operation_id)
            if op is not None:
                op.status = (
                    OperationStatus.SUCCESS if result.success else OperationStatus.FAILED
                )
                op.completed_at = datetime.now(timezone.utc)
                op.plan_output = result.stdout
                if not result.success:
                    op.error_message = result.stderr
                await db.commit()
    finally:
        await release_org_lock(lock, str(operation_id))


async def _run_plan(
    operation_id: uuid.UUID,
    lock: str,
    workspace: TerraformWorkspace,
    psk_vars: dict[str, str],
) -> None:
    runner = TerraformRunner(
        workspace.work_dir,
        operation_id=str(operation_id),
        extra_tf_vars=psk_vars,
    )
    init = await runner.init()
    if not init.success:
        await _finish(operation_id, lock, init)
        return
    await _finish(operation_id, lock, await runner.plan())


async def _run_apply(
    operation_id: uuid.UUID, lock: str, workspace: TerraformWorkspace
) -> None:
    runner = TerraformRunner(workspace.work_dir, operation_id=str(operation_id))
    await _finish(operation_id, lock, await runner.apply())
