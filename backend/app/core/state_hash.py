"""Canonical hashing of Terraform state for deduplication.

The raw ``terraform.tfstate`` file changes on every apply (``serial``
increments, ``lineage`` may change after re-init) even when no managed
resource actually changed. To detect "no real change" we hash a
canonical projection produced by ``terraform show -json``.

Volatile / noise normalised before hashing:
  * top-level ``terraform_version`` / ``format_version``
  * each resource's ``sensitive_values`` dropped
  * ``None``, ``[]``, ``{}`` collapsed to a single sentinel
    (some VCD provider attributes flip between ``null`` and ``[]``
    on no-op applies; both mean "unset" semantically).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


_VOLATILE_TOP_KEYS = {"terraform_version", "format_version"}
_VOLATILE_RESOURCE_KEYS = {"sensitive_values"}


def _is_empty(v):
    return v is None or v == [] or v == {} or v == ""


def _canonicalize(obj):
    """Return a representation with deterministic ordering, noise stripped,
    and null/empty containers collapsed to a single sentinel string."""
    if isinstance(obj, dict):
        return {
            k: _canonicalize(v)
            for k, v in sorted(obj.items())
            if k not in _VOLATILE_RESOURCE_KEYS and not _is_empty(v)
        }
    if isinstance(obj, list):
        if not obj:
            return "__EMPTY__"
        return [_canonicalize(v) for v in obj]
    if obj is None:
        return "__EMPTY__"
    return obj


def hash_state_json(show_json: dict) -> str:
    """Compute SHA-256 over canonical JSON of ``terraform show -json`` output."""
    pruned = {k: v for k, v in show_json.items() if k not in _VOLATILE_TOP_KEYS}
    canon = _canonicalize(pruned)
    encoded = json.dumps(canon, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def compute_state_hash(work_dir: Path, terraform_binary: str) -> str:
    """Run ``terraform show -json`` in ``work_dir`` and hash the output.

    Raises RuntimeError if terraform fails or output is not valid JSON.
    """
    proc = await asyncio.create_subprocess_exec(
        terraform_binary, "show", "-json",
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"terraform show -json failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', 'replace')[:500]}"
        )
    try:
        data = json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"terraform show -json produced invalid JSON: {exc}")
    return hash_state_json(data)
