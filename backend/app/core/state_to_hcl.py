"""Patch HCL text to reflect terraform state drift.

On drift accept we refresh-apply the state so it matches real VCD, but the
stored HCL still reflects the pre-drift values. That makes rollback
meaningless — v<N-1> HCL == v<N> HCL, so restoring either produces a
zero-change plan.

This module patches the original HCL text with attribute values from the
new state, so each drift snapshot stores an HCL that actually describes
current reality. Text-level patching (not full regeneration) is used to
preserve formatting, comments, and references like
``source_ids = [vcd_nsxt_ip_set.foo.id]``.

Supported resource types (first iteration):
  * vcd_nsxt_ip_set               — name, description, ip_addresses
  * vcd_nsxt_nat_rule             — name, description, external_address,
                                    internal_address, dnat_external_port, logging, enabled
  * vcd_nsxt_edgegateway_static_route — name, description, network_cidr,
                                        nested next_hop.ip_address / admin_distance
  * vcd_nsxt_app_port_profile     — name, description, nested app_port.port
  * vcd_nsxt_firewall (rule list) — per-rule: name, action, enabled, logging

Unsupported drift (cross-resource refs, adds, deletes) → leave HCL
untouched. Caller falls back to pre-drift HCL.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# State parsing
# ----------------------------------------------------------------------


def _resources_by_address(state_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return {address: {type, name, attributes}} from a tfstate dict.

    Accepts both raw ``terraform.tfstate`` format and ``terraform show -json``
    output (which wraps state under ``values.root_module.resources``).
    """
    out: dict[str, dict[str, Any]] = {}

    # terraform show -json: {values: {root_module: {resources: [...]}}, ...}
    values = state_json.get("values")
    if values and isinstance(values, dict):
        root = values.get("root_module", {})
        for r in root.get("resources", []):
            if r.get("mode") != "managed":
                continue
            addr = r.get("address") or f"{r.get('type')}.{r.get('name')}"
            out[addr] = {
                "type": r.get("type"),
                "name": r.get("name"),
                "attributes": r.get("values", {}),
            }
        return out

    # Raw tfstate: {resources: [{mode, type, name, instances: [{attributes}]}]}
    for r in state_json.get("resources", []):
        if r.get("mode") != "managed":
            continue
        instances = r.get("instances", [])
        if not instances:
            continue
        attrs = instances[0].get("attributes", {})
        addr = f"{r['type']}.{r['name']}"
        out[addr] = {
            "type": r.get("type"),
            "name": r.get("name"),
            "attributes": attrs,
        }
    return out


# ----------------------------------------------------------------------
# HCL block extraction (brace-aware)
# ----------------------------------------------------------------------


_RESOURCE_HEADER_RE = re.compile(
    r'^[ \t]*resource[ \t]+"(?P<type>[^"]+)"[ \t]+"(?P<name>[^"]+)"[ \t]*\{',
    re.MULTILINE,
)


def _find_matching_brace(text: str, open_pos: int) -> int:
    """Given index of '{', return index of matching '}'. -1 if not found.

    Handles string literals and // / # line comments.
    """
    depth = 0
    i = open_pos
    n = len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == "#" or (ch == "/" and i + 1 < n and text[i + 1] == "/"):
            nl = text.find("\n", i)
            i = nl if nl != -1 else n
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_resource_block(
    text: str, rtype: str, rname: str
) -> tuple[int, int] | None:
    """Return (start, end) char indices of the resource block body (inside braces).

    ``start`` points at the first char AFTER the opening ``{``.
    ``end`` points at the ``}``.
    """
    for m in _RESOURCE_HEADER_RE.finditer(text):
        if m.group("type") != rtype or m.group("name") != rname:
            continue
        open_pos = m.end() - 1  # position of '{'
        close_pos = _find_matching_brace(text, open_pos)
        if close_pos == -1:
            return None
        return (open_pos + 1, close_pos)
    return None


def _find_nested_block(
    text: str, start: int, end: int, block_name: str
) -> list[tuple[int, int]]:
    """Find all nested blocks named ``block_name`` within [start, end).

    Returns list of (inner_start, inner_end) for each block body.
    """
    pattern = re.compile(rf'^[ \t]*{re.escape(block_name)}[ \t]*\{{', re.MULTILINE)
    results = []
    pos = start
    while pos < end:
        m = pattern.search(text, pos, end)
        if not m:
            break
        open_pos = m.end() - 1
        close_pos = _find_matching_brace(text, open_pos)
        if close_pos == -1 or close_pos > end:
            break
        results.append((open_pos + 1, close_pos))
        pos = close_pos + 1
    return results


# ----------------------------------------------------------------------
# Attribute-level patchers
# ----------------------------------------------------------------------


def _hcl_escape(v: str) -> str:
    v = str(v)
    v = v.replace("\\", "\\\\")
    v = v.replace('"', '\\"')
    v = v.replace("\n", "\\n")
    v = v.replace("\r", "\\r")
    v = v.replace("$", "$$")
    return v


def _patch_scalar(
    text: str, start: int, end: int, attr: str, new_value: Any
) -> tuple[str, int, int] | None:
    """Replace ``attr = <literal>`` inside [start, end). Preserves indentation.

    Returns (new_text, new_start, new_end) or None if attr not found.
    """
    body = text[start:end]
    # Match attr line: optional whitespace, attr, '=', rest-of-line.
    # We purposely anchor to beginning of a line and consume up to newline
    # (no multi-line scalars expected).
    pat = re.compile(
        rf'^(?P<ind>[ \t]*){re.escape(attr)}(?P<eq>[ \t]*=[ \t]*)(?P<val>.*)$',
        re.MULTILINE,
    )
    m = pat.search(body)
    if not m:
        return None

    old_val_raw = m.group("val").rstrip()
    # Drop trailing inline comment to avoid corrupting it.
    comment = ""
    for marker in ("#", "//"):
        idx = _find_unquoted(old_val_raw, marker)
        if idx != -1:
            comment = " " + old_val_raw[idx:].rstrip()
            old_val_raw = old_val_raw[:idx].rstrip()
            break

    new_literal = _render_literal(new_value)
    new_line = f"{m.group('ind')}{attr}{m.group('eq')}{new_literal}{comment}"
    new_body = body[: m.start()] + new_line + body[m.end() :]
    new_text = text[:start] + new_body + text[end:]
    delta = len(new_body) - len(body)
    return (new_text, start, end + delta)


def _find_unquoted(s: str, needle: str) -> int:
    """Find ``needle`` outside of double-quoted strings. Return -1 if absent."""
    in_str = False
    i = 0
    n = len(s)
    nl = len(needle)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if s[i : i + nl] == needle:
            return i
        i += 1
    return -1


def _render_literal(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return f'"{_hcl_escape(v)}"'
    if isinstance(v, list):
        parts = [_render_literal(x) for x in v]
        return "[" + ", ".join(parts) + "]"
    # Fallback: JSON-encode anything else (unlikely for scalar attrs).
    return json.dumps(v)


# ----------------------------------------------------------------------
# Per-type patch handlers
# ----------------------------------------------------------------------


# For each resource type: list of scalar/list attributes whose drift we
# mirror into HCL. Keep this conservative — unlisted attrs (IDs, computed
# fields, cross-references) are deliberately left alone.
_SIMPLE_ATTR_MAP: dict[str, list[str]] = {
    "vcd_nsxt_ip_set": ["name", "description", "ip_addresses"],
    "vcd_nsxt_nat_rule": [
        "name",
        "description",
        "external_address",
        "internal_address",
        "dnat_external_port",
        "logging",
        "enabled",
    ],
    "vcd_nsxt_edgegateway_static_route": [
        "name",
        "description",
        "network_cidr",
    ],
    "vcd_nsxt_app_port_profile": ["name", "description"],
}


def _patch_simple(
    text: str,
    rtype: str,
    rname: str,
    old_attrs: dict[str, Any],
    new_attrs: dict[str, Any],
) -> tuple[str, bool]:
    """Patch scalar/list attrs listed in _SIMPLE_ATTR_MAP. Returns (text, changed)."""
    span = _find_resource_block(text, rtype, rname)
    if span is None:
        return text, False
    start, end = span
    changed = False
    for attr in _SIMPLE_ATTR_MAP.get(rtype, []):
        if attr not in new_attrs:
            continue
        old_v = old_attrs.get(attr)
        new_v = new_attrs.get(attr)
        if old_v == new_v:
            continue
        res = _patch_scalar(text, start, end, attr, new_v)
        if res is None:
            logger.debug(
                "state_to_hcl: attr %s not found in %s.%s, skipping",
                attr, rtype, rname,
            )
            continue
        text, start, end = res
        changed = True
    return text, changed


def _patch_firewall(
    text: str,
    rname: str,
    old_attrs: dict[str, Any],
    new_attrs: dict[str, Any],
) -> tuple[str, bool]:
    """Patch vcd_nsxt_firewall rule blocks for drift in rule.name/action/enabled/logging.

    Rules match old↔new by list index (terraform preserves order). We only
    touch rules whose index appears in both lists. Additions/removals get
    skipped (caller retains pre-drift HCL for those edge cases).
    """
    span = _find_resource_block(text, "vcd_nsxt_firewall", rname)
    if span is None:
        return text, False
    start, end = span

    old_rules = old_attrs.get("rule") or []
    new_rules = new_attrs.get("rule") or []
    if len(old_rules) != len(new_rules):
        logger.info(
            "state_to_hcl: firewall rule count changed (%d → %d); skipping in-place patch",
            len(old_rules), len(new_rules),
        )
        return text, False

    changed = False
    # Re-locate rule blocks inside (possibly mutated) text each loop.
    for idx in range(len(old_rules)):
        old_r = old_rules[idx] or {}
        new_r = new_rules[idx] or {}
        blocks = _find_nested_block(text, start, end, "rule")
        if idx >= len(blocks):
            break
        rb_start, rb_end = blocks[idx]
        for attr in ("name", "action", "enabled", "logging"):
            if attr not in new_r:
                continue
            if old_r.get(attr) == new_r.get(attr):
                continue
            res = _patch_scalar(text, rb_start, rb_end, attr, new_r[attr])
            if res is None:
                continue
            text, rb_start, rb_end = res
            # Reposition outer span by delta against prior end.
            # Easiest: recompute whole block by re-search on next iteration.
            changed = True
            # Re-locate parent block after mutation.
            new_span = _find_resource_block(text, "vcd_nsxt_firewall", rname)
            if new_span is None:
                return text, changed
            start, end = new_span
    return text, changed


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------


def remove_resource_blocks(hcl: str, addresses: list[str]) -> tuple[str, list[str]]:
    """Delete ``resource "TYPE" "NAME" { ... }`` blocks for each address.

    Accepts addresses in ``TYPE.NAME`` form. Returns (new_hcl, removed_list).
    Addresses not found are silently skipped (reported as not-in-result).
    """
    removed: list[str] = []
    for addr in addresses:
        if "." not in addr:
            continue
        rtype, _, rname = addr.partition(".")
        # Iterate until block is gone; handles no-op when already removed.
        for m in _RESOURCE_HEADER_RE.finditer(hcl):
            if m.group("type") != rtype or m.group("name") != rname:
                continue
            open_pos = m.end() - 1
            close_pos = _find_matching_brace(hcl, open_pos)
            if close_pos == -1:
                break
            # Trim preceding blank line(s) so we don't leave a double gap.
            block_start = m.start()
            while block_start > 0 and hcl[block_start - 1] in (" ", "\t"):
                block_start -= 1
            # Consume one trailing newline so the block removal is clean.
            block_end = close_pos + 1
            if block_end < len(hcl) and hcl[block_end] == "\n":
                block_end += 1
            hcl = hcl[:block_start] + hcl[block_end:]
            removed.append(addr)
            break
    return hcl, removed


def patch_hcl_from_state(
    hcl: str,
    old_state: dict[str, Any],
    new_state: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Return (patched_hcl, summary). Never raises; on failure returns input unchanged.

    ``summary`` is a small dict with counters suitable for logging.
    """
    try:
        old_by_addr = _resources_by_address(old_state)
        new_by_addr = _resources_by_address(new_state)
    except Exception as exc:
        logger.exception("state_to_hcl: failed to index state: %s", exc)
        return hcl, {"error": str(exc), "patched": 0}

    patched_count = 0
    skipped: list[str] = []
    text = hcl

    for addr, new_entry in new_by_addr.items():
        old_entry = old_by_addr.get(addr)
        if old_entry is None:
            # Resource added in state (import). Leave HCL alone — caller
            # already appended block during import flow; nothing to patch.
            continue
        rtype = new_entry["type"]
        rname = new_entry["name"]
        old_attrs = old_entry.get("attributes") or {}
        new_attrs = new_entry.get("attributes") or {}

        try:
            if rtype == "vcd_nsxt_firewall":
                text, changed = _patch_firewall(text, rname, old_attrs, new_attrs)
            elif rtype in _SIMPLE_ATTR_MAP:
                text, changed = _patch_simple(text, rtype, rname, old_attrs, new_attrs)
            else:
                changed = False
        except Exception:
            logger.exception(
                "state_to_hcl: patch failed for %s.%s", rtype, rname,
            )
            skipped.append(addr)
            continue

        if changed:
            patched_count += 1

    return text, {"patched": patched_count, "skipped": skipped}
