"""Rewrite IPv4 addresses when a spec moves to another cloud.

A migrated edge keeps its internal networks but almost never keeps its
public address: the destination cloud allocates its own.  Every NAT rule
and IP set that names the old address has to be rewritten, and missing
one leaves a rule pointing at an address the destination does not own.

Replacement is token-aware, never a substring swap.  ``91.185.11.1`` is a
prefix of ``91.185.11.10``, so a naive ``str.replace`` would corrupt the
longer address while appearing to work.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections import Counter

from app.schemas.deployment_spec import DeploymentSpec

logger = logging.getLogger(__name__)

# A dotted quad that is not part of a longer dotted sequence. The guards on
# both sides are what make "91.185.11.1" not match inside "91.185.11.10".
_IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")

# Where an address was found, most-likely-needs-changing first.
EXTERNAL = "external"
IP_SET = "ip_set"
INTERNAL = "internal"
ROUTE = "route"

_KIND_ORDER = {EXTERNAL: 0, IP_SET: 1, ROUTE: 2, INTERNAL: 3}


def is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False


def _addresses_in(text: str) -> list[str]:
    return _IPV4_RE.findall(text or "")


def remap_text(text: str, mapping: dict[str, str]) -> str:
    """Replace whole addresses in ``text``, leaving prefixes and ports alone."""
    if not text or not mapping:
        return text
    return _IPV4_RE.sub(lambda m: mapping.get(m.group(1), m.group(1)), text)


def _remap_list(values: list[str], mapping: dict[str, str]) -> list[str]:
    return [remap_text(v, mapping) for v in values]


def collect_addresses(spec: DeploymentSpec) -> list[dict]:
    """Every distinct IPv4 in the spec, with where and how often it appears.

    The UI uses this to pre-fill the remap table so nobody has to grep the
    HCL for addresses that need changing.
    """
    kinds: dict[str, set[str]] = {}
    counts: Counter = Counter()
    used_by: dict[str, list[str]] = {}

    def note(addr: str, kind: str, where: str) -> None:
        counts[addr] += 1
        kinds.setdefault(addr, set()).add(kind)
        refs = used_by.setdefault(addr, [])
        if where and where not in refs and len(refs) < 5:
            refs.append(where)

    for s in spec.ip_sets:
        for entry in s.ip_addresses:
            for a in _addresses_in(entry):
                note(a, IP_SET, f"IP set {s.name}")

    for r in spec.nat_rules:
        for a in _addresses_in(r.external_address):
            note(a, EXTERNAL, f"NAT {r.name}")
        for a in _addresses_in(r.internal_address):
            note(a, INTERNAL, f"NAT {r.name}")
        for a in _addresses_in(r.snat_destination_address):
            note(a, INTERNAL, f"NAT {r.name}")

    for route in spec.static_routes:
        for a in _addresses_in(route.network_cidr):
            note(a, ROUTE, f"route {route.name}")
        for hop in route.next_hops:
            for a in _addresses_in(hop.ip_address):
                note(a, ROUTE, f"route {route.name}")

    out = [
        {
            "address": addr,
            # An address used both ways is reported by its most exposed use.
            "kind": sorted(kinds[addr], key=lambda k: _KIND_ORDER[k])[0],
            "occurrences": counts[addr],
            "used_by": used_by.get(addr, []),
        }
        for addr in counts
    ]
    out.sort(key=lambda d: (_KIND_ORDER[d["kind"]], -d["occurrences"], d["address"]))
    return out


def apply_mapping(spec: DeploymentSpec, mapping: dict[str, str]) -> DeploymentSpec:
    """Return a copy of ``spec`` with every mapped address rewritten.

    Raises:
        ValueError: a key or value is not a valid IPv4 address.
    """
    if not mapping:
        return spec

    for old, new in mapping.items():
        if not is_valid_ipv4(old):
            raise ValueError(f"{old!r} is not a valid IPv4 address")
        if not is_valid_ipv4(new):
            raise ValueError(f"{new!r} is not a valid IPv4 address (mapped from {old})")

    updated = spec.model_copy(deep=True)

    for s in updated.ip_sets:
        s.ip_addresses = _remap_list(s.ip_addresses, mapping)

    for r in updated.nat_rules:
        r.external_address = remap_text(r.external_address, mapping)
        r.internal_address = remap_text(r.internal_address, mapping)
        r.snat_destination_address = remap_text(r.snat_destination_address, mapping)

    for route in updated.static_routes:
        route.network_cidr = remap_text(route.network_cidr, mapping)
        for hop in route.next_hops:
            hop.ip_address = remap_text(hop.ip_address, mapping)

    logger.info(
        "ip_remap applied pairs=%d: %s",
        len(mapping),
        ", ".join(f"{o}->{n}" for o, n in sorted(mapping.items())),
    )
    return updated
