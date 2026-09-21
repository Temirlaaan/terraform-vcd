"""Tests for the IPsec migration tab's backend.

The property that matters most here: a pre-shared key must not leave the
backend towards the browser. Everything the tab shows is derived from the
tunnel, never the key itself.
"""

import pytest

from app.api.routes.ipsec_migration import _to_out, _warnings


SECRET = "TopSecretKey12345"


def _tunnel(**over):
    base = {
        "name": "TTK - Crop91",
        "slug": "ttk_crop91",
        "enabled": True,
        "local_ip": "87.255.215.204",
        "peer_ip": "212.98.183.16",
        "remote_id": "10.168.202.2",
        "local_networks": ["10.0.10.0/24"],
        "remote_networks": ["192.168.14.0/23"],
        "encryption": "AES_256",
        "digest": "SHA2_256",
        "dh_group": "GROUP14",
        "ike_version": "IKE_V2",
        "pfs": True,
        "psk": SECRET,
        "unsupported": [],
        "migratable": True,
    }
    base.update(over)
    return base


class TestPskNeverLeavesTheBackend:
    def test_psk_absent_from_serialised_tunnel(self):
        payload = _to_out(_tunnel()).model_dump_json()
        assert SECRET not in payload

    def test_no_psk_field_exists_at_all(self):
        assert "psk" not in _to_out(_tunnel()).model_dump()

    def test_readability_is_reported_as_a_boolean(self):
        assert _to_out(_tunnel(psk=SECRET)).psk_readable is True
        assert _to_out(_tunnel(psk=None)).psk_readable is False


class TestTunnelProjection:
    def test_source_state_is_reported_separately(self):
        """Tunnels are always created disabled, so the UI has to show what
        the source state was rather than what will be applied."""
        assert _to_out(_tunnel(enabled=True)).enabled_on_source is True
        assert _to_out(_tunnel(enabled=False)).enabled_on_source is False

    def test_reasons_are_carried(self):
        out = _to_out(_tunnel(migratable=False, unsupported=["3des has no equivalent"]))
        assert out.migratable is False
        assert out.unsupported == ["3des has no equivalent"]


class TestWarnings:
    def test_skipped_tunnels_are_announced(self):
        msgs = " ".join(_warnings([], [_tunnel(migratable=False)]))
        assert "cannot be migrated" in msgs

    def test_missing_key_is_announced(self):
        msgs = " ".join(_warnings([_tunnel(psk=None)], []))
        assert "pre-shared key" in msgs
        assert "TTK - Crop91" in msgs

    def test_disabled_by_default_is_always_stated(self):
        msgs = " ".join(_warnings([_tunnel()], []))
        assert "disabled" in msgs

    def test_no_warning_noise_when_nothing_to_do(self):
        assert _warnings([], []) == []
