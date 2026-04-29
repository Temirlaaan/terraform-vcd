"""Aria attribution: embed dashboard kc_user into VCD-visible fields.

This module is the single source of truth for the
``[by:<kc_user>:<op_id>]`` decoration prefix. Renderers and workspace
writers call ``retag_hcl()`` post-render to inject (or refresh) the
prefix on every ``description = "..."`` line in a piece of HCL. The
prefix is idempotent — re-tagging text that already carries one
replaces it rather than compounding.



Phase 8 design: every TF-managed resource description gets a deterministic
prefix `[by:<kc_user>:<op_id>] <user_text>`. VCD inventory + task events
carry the prefix; VMware Aria indexes it by description, so support
queries can resolve `who?` without leaving Aria.

The prefix is a runtime decoration only — saved spec.json keeps clean
user text. Renderers receive an `Attribution` instance and call
``tag()`` per description; editor-side parsers call ``strip()`` to
hide the prefix from the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `[by:<user>:<op>] ` — colon-delimited so users can't trivially craft a
# matching prefix in their own text (operator-side trust is partial).
_PREFIX_RE = re.compile(
    r"^\[by:(?P<user>[^:\]]+):(?P<op>[^\]]+)\]\s?"
)


@dataclass(frozen=True)
class Attribution:
    """Carries who+which-op into the HCL renderer.

    ``kc_username`` is the Keycloak ``preferred_username`` claim (e.g.
    ``tadm.ilzhanov``). ``op_id`` is the dashboard ``Operation.id`` UUID
    (string form). Both are short enough to fit comfortably in any VCD
    description field.

    For cron-driven flows (drift sync) where no human user is involved,
    pass ``kc_username='drift-sync-cron'`` and ``op_id`` = the
    drift_report id so Aria still gets a coherent attribution.
    """

    kc_username: str
    op_id: str

    def prefix(self) -> str:
        return f"[by:{self.kc_username}:{self.op_id}]"


def tag(user_text: str | None, attribution: Attribution | None) -> str:
    """Prepend the attribution prefix to a description string.

    - Returns the input unchanged when ``attribution`` is None.
    - Strips any pre-existing dashboard prefix first so re-renders
      don't compound (e.g. editor saves on top of an apply that
      already tagged the description).
    - Empty / None ``user_text`` becomes just the prefix (with a
      trailing space trimmed).
    """
    text = "" if user_text is None else str(user_text)
    if attribution is None:
        return text

    text = strip(text)
    pfx = attribution.prefix()
    if not text:
        return pfx
    return f"{pfx} {text}"


def strip(text: str | None) -> str:
    """Remove a leading ``[by:...:...]`` prefix.

    Used by the editor parsers (``deployment_spec_from_state``,
    ``editor-data`` route) so the form shows the user's clean text
    rather than the runtime decoration.
    """
    if text is None:
        return ""
    s = str(text)
    m = _PREFIX_RE.match(s)
    if m is None:
        return s
    return s[m.end():]


def is_tagged(text: str | None) -> bool:
    """True when ``text`` carries a dashboard attribution prefix."""
    if text is None:
        return False
    return bool(_PREFIX_RE.match(str(text)))


# Synthetic users for non-interactive callers.
DRIFT_SYNC_USER = "drift-sync-cron"
SYSTEM_USER = "tf-dashboard-system"


# Matches `description = "..."` HCL lines (single-quoted-equivalent in HCL
# is the standard double-quoted form). The string body honours backslash
# escapes so quoted-quotes don't terminate early — same rule HCL itself
# uses. The capturing groups are (lhs, body) so the substitution can
# preserve indentation + spacing while rewriting only the body.
_DESC_RE = re.compile(
    r'(\s*description\s*=\s*)"((?:[^"\\]|\\.)*)"'
)


def _hcl_unescape(s: str) -> str:
    # Reverse of `_hcl_escape` in `core.hcl_generator`. Only handles the
    # escapes that HCL itself uses for double-quoted strings: \\, \", \n,
    # \r, $$. Anything else passes through unchanged — the prefix
    # injection only needs to round-trip these forms safely.
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "\\":
                out.append("\\")
            elif nxt == '"':
                out.append('"')
            elif nxt == "n":
                out.append("\n")
            elif nxt == "r":
                out.append("\r")
            else:
                out.append(c)
                out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out).replace("$$", "$")


def _hcl_escape(s: str) -> str:
    # Mirror of `core.hcl_generator._hcl_escape`. Duplicated here to
    # avoid an import cycle with `hcl_generator` (which imports `core`).
    v = s.replace("\\", "\\\\").replace('"', '\\"')
    v = v.replace("\n", "\\n").replace("\r", "\\r").replace("$", "$$")
    return v


def retag_hcl(hcl: str, attribution: Attribution | None) -> str:
    """Rewrite every ``description = "..."`` line to carry the prefix.

    Idempotent: an existing dashboard prefix is replaced with the new
    attribution before the new prefix is prepended. Resources without a
    description line are unaffected. HCL escaping is preserved.
    """
    if attribution is None or not hcl:
        return hcl

    def repl(m: re.Match[str]) -> str:
        lhs, body = m.group(1), m.group(2)
        plain = _hcl_unescape(body)
        retagged = tag(plain, attribution)
        return f'{lhs}"{_hcl_escape(retagged)}"'

    return _DESC_RE.sub(repl, hcl)


def strip_descriptions_in_hcl(hcl: str) -> str:
    """Strip ``[by:...]`` prefixes from every ``description = "..."`` line.

    Used by the editor's ``GET /hcl`` so the user sees clean text rather
    than the runtime decoration. HCL escaping is preserved.
    """
    if not hcl:
        return hcl

    def repl(m: re.Match[str]) -> str:
        lhs, body = m.group(1), m.group(2)
        plain = _hcl_unescape(body)
        return f'{lhs}"{_hcl_escape(strip(plain))}"'

    return _DESC_RE.sub(repl, hcl)
