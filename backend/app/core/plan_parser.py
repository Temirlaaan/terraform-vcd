"""Parse ``terraform show -json plan.bin`` output for drift classification.

We only care about ``resource_drift`` (refresh-only reveals divergence
between stored state and real infra):

- actions == ["update"] → modification
- actions == ["delete"] → deletion
- actions == ["no-op"] or ["read"] → ignored (refresh noise)

Additions are NOT reported here — refresh-only cannot see resources that
aren't already in state. Use ``detect_additions`` (VCD enumeration) instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class DriftEntry:
    address: str
    resource_type: str
    name: str
    action: str
    before: dict | None
    after: dict | None

    def as_json(self) -> dict:
        return {
            "address": self.address,
            "type": self.resource_type,
            "name": self.name,
            "action": self.action,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class ParsedPlan:
    modifications: list[DriftEntry]
    deletions: list[DriftEntry]

    @property
    def has_changes(self) -> bool:
        return bool(self.modifications or self.deletions)


_INTERESTING_ACTIONS = {"update", "delete", "create"}


def parse_show_json(show_json: str) -> ParsedPlan:
    """Parse ``terraform show -json <planfile>`` stdout.

    ``create`` actions inside ``resource_drift`` are unusual (real Terraform
    uses them in resource_changes, not drift) but we map them to mods to
    stay defensive — refresh-only should never propose creates.
    """
    data = json.loads(show_json)
    mods: list[DriftEntry] = []
    dels: list[DriftEntry] = []

    for entry in data.get("resource_drift") or []:
        change = entry.get("change") or {}
        actions = change.get("actions") or []
        if not any(a in _INTERESTING_ACTIONS for a in actions):
            continue
        drift = DriftEntry(
            address=entry.get("address", ""),
            resource_type=entry.get("type", ""),
            name=entry.get("name", ""),
            action=",".join(actions),
            before=change.get("before"),
            after=change.get("after"),
        )
        if "delete" in actions:
            dels.append(drift)
        else:
            mods.append(drift)

    return ParsedPlan(modifications=mods, deletions=dels)
