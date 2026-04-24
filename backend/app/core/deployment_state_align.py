"""Align Terraform state addresses when a deployment's HCL is rebuilt.

When the editor rewrites a deployment's ``main.tf`` via PUT /spec, the
resource addresses (`<type>.<slug>`) can change even though the VCD
resource names stay the same — for example, migration-generated HCL
uses ``<proto>_<port>`` slugs (``tcp_53``) while the editor rebuild
uses ``_slug(name)`` (``ttc_fw_tcp_53``). Next `terraform plan` would
then see the old address as orphaned (``destroy``) and the new one as
missing (``create``), even though the same real resource backs both.

This module renames state entries to match the new HCL before the
rebuilt main.tf is persisted. Matching is done by the ``name`` attribute
inside each HCL resource block, which is stable across slug schemes.

State mutation lands in the deployment's live state key in MinIO (S3
backend). If a state mv fails (e.g. old address not actually in state),
the error is logged and the rest proceed — alignment is best-effort.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from app.core import version_store
from app.core.tf_import import parse_hcl_resources
from app.core.tf_runner import TerraformRunner
from app.core.tf_workspace import TerraformWorkspace

if TYPE_CHECKING:
    from app.core.tf_import import HclResource

logger = logging.getLogger(__name__)


def _name_to_address(hcl: str) -> dict[tuple[str, str], str]:
    """Map ``(tf_type, vcd_name)`` -> ``tf_type.tf_label`` for a given HCL."""
    out: dict[tuple[str, str], str] = {}
    for r in parse_hcl_resources(hcl):
        if r.vcd_name is None:
            continue
        key = (r.tf_type, r.vcd_name)
        # On duplicate names inside a single HCL the first wins. The
        # DeploymentSpec validator rejects duplicates on save, so this
        # only matters for legacy/migration HCL read as the "old" side.
        out.setdefault(key, r.address)
    return out


def compute_moves(old_hcl: str, new_hcl: str) -> list[tuple[str, str]]:
    """Return ``[(old_address, new_address), ...]`` pairs to run as state mv."""
    old_map = _name_to_address(old_hcl)
    new_map = _name_to_address(new_hcl)

    moves: list[tuple[str, str]] = []
    for key, old_addr in old_map.items():
        new_addr = new_map.get(key)
        if new_addr and new_addr != old_addr:
            moves.append((old_addr, new_addr))
    return moves


def _render_provider_tf(deployment_id: uuid.UUID) -> str:
    """Render provider.tf with backend pointing to deployment's live state key.

    Duplicates the logic in ``app.api.routes.deployment_hcl._render_provider_tf``
    and ``app.core.rollback._render_provider_tf`` to keep this module free
    of route-layer imports.
    """
    from jinja2 import Environment, FileSystemLoader

    tpl_dir = (
        Path(__file__).resolve().parent.parent / "templates" / "migration"
    )
    jenv = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = jenv.get_template("provider.tf.j2")
    return tpl.render(
        state_key=version_store.state_key_for_deployment(deployment_id)
    )


async def align_state_to_hcl(
    deployment_id: uuid.UUID,
    org_name: str,
    old_hcl: str,
    new_hcl: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Run ``terraform state mv`` for every name whose TF address changed.

    Returns ``(applied_moves, errors)``. Errors are non-fatal: alignment
    is best-effort and a failure here just means the next plan will show
    a destroy+create for the misaligned resource.
    """
    moves = compute_moves(old_hcl, new_hcl)
    if not moves:
        return [], []

    operation_id = uuid.uuid4()
    workspace = TerraformWorkspace(org_name, operation_id)
    workspace.work_dir.mkdir(parents=True, exist_ok=True)

    # Write NEW HCL so `terraform init` sees the provider constraints
    # that match the desired state shape after alignment.
    (workspace.work_dir / "main.tf").write_text(new_hcl, encoding="utf-8")
    (workspace.work_dir / "provider.tf").write_text(
        _render_provider_tf(deployment_id), encoding="utf-8"
    )

    runner = TerraformRunner(workspace.work_dir, operation_id=str(operation_id))

    errors: list[str] = []
    try:
        init_result = await runner.init()
        if not init_result.success:
            msg = f"state-align init failed: {init_result.stderr[:500]}"
            logger.warning(msg)
            return [], [msg]

        state_list = await runner._exec(
            "state", "list", "-no-color", emit_exit=False
        )
        managed = (
            set(state_list.stdout.strip().splitlines())
            if state_list.success
            else set()
        )

        applied: list[tuple[str, str]] = []
        for old_addr, new_addr in moves:
            if old_addr not in managed:
                logger.info(
                    "state-align: skip %s (not in state) deployment=%s",
                    old_addr, deployment_id,
                )
                continue
            if new_addr in managed:
                # New address already tracks a real resource — state mv
                # would collide. Remove the orphan old address so plan
                # only sees the new one.
                result = await runner._exec(
                    "state", "rm", "-no-color", old_addr, emit_exit=False
                )
                if result.success:
                    logger.info(
                        "state-align: rm duplicate %s (new %s already managed) deployment=%s",
                        old_addr, new_addr, deployment_id,
                    )
                    applied.append((old_addr, f"<removed:duplicate_of {new_addr}>"))
                else:
                    errors.append(
                        f"state rm failed for {old_addr}: {result.stderr[:500]}"
                    )
                continue
            result = await runner._exec(
                "state", "mv", "-no-color", old_addr, new_addr, emit_exit=False
            )
            if result.success:
                logger.info(
                    "state-align: mv %s -> %s deployment=%s",
                    old_addr, new_addr, deployment_id,
                )
                applied.append((old_addr, new_addr))
            else:
                errors.append(
                    f"state mv failed for {old_addr} -> {new_addr}: {result.stderr[:500]}"
                )
        return applied, errors
    finally:
        workspace.cleanup()
