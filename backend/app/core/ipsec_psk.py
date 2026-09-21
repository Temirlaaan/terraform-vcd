"""Pre-shared keys for IPsec tunnels: where they come from, per run.

The resource requires ``pre_shared_key`` and the project forbids secrets
in HCL, so every plan and apply has to supply the keys as ``TF_VAR_*``.

There is no separate secret store, deliberately. Terraform already writes
these keys into state in the clear — ``sensitive`` only hides them from
CLI output — and that state is already in MinIO behind an admin-only
endpoint. A second copy in the database would not remove that exposure,
it would add another place to leak from, plus an encryption key to rotate.

So the state is the store:

  * the first apply takes keys from the source VCD, read once during
    migration and passed straight through;
  * everything after — later applies, rollback, the nightly drift job —
    reads them back out of the deployment's own state.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_TUNNEL_TYPE = "vcd_nsxt_ipsec_vpn_tunnel"


def psk_vars_from_tunnels(tunnels: list[dict]) -> dict[str, str]:
    """Build TF_VAR names from normalized tunnels, for the first apply.

    Expects the slugged tunnels the generator rendered, so variable names
    line up with ``var.psk_<slug>`` in the HCL.
    """
    out: dict[str, str] = {}
    for tunnel in tunnels:
        slug, psk = tunnel.get("slug"), tunnel.get("psk")
        if slug and psk:
            out[f"psk_{slug}"] = psk
    return out


def psk_vars_from_state(state: str | dict) -> dict[str, str]:
    """Recover keys from a terraform state document.

    Returns ``{"psk_<resource label>": key}``. The label is the terraform
    resource name, which is the same slug the generator used, so the names
    match what the HCL declares.

    A tunnel present in state without a key yields nothing rather than an
    empty string: an empty ``pre_shared_key`` would be accepted by
    terraform and produce a tunnel that never establishes.
    """
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError as exc:
            raise ValueError(f"state is not valid JSON: {exc}") from exc

    out: dict[str, str] = {}
    missing: list[str] = []

    for resource in state.get("resources", []):
        if resource.get("type") != _TUNNEL_TYPE:
            continue
        label = resource.get("name")
        if not label:
            continue
        for instance in resource.get("instances", []):
            psk = (instance.get("attributes") or {}).get("pre_shared_key")
            if psk:
                out[f"psk_{label}"] = psk
            else:
                missing.append(label)

    if missing:
        logger.warning(
            "no pre_shared_key in state for tunnel(s): %s — terraform will "
            "refuse to plan without them",
            ", ".join(sorted(set(missing))),
        )
    return out
