"""Tests for PSK sourcing — keys travel as TF_VAR_*, never in HCL."""

import json

import pytest

from app.core.ipsec_psk import psk_vars_from_state, psk_vars_from_tunnels


def _state(*tunnels):
    return {
        "version": 4,
        "resources": [
            {"type": "vcd_nsxt_ip_set", "name": "dmz",
             "instances": [{"attributes": {"name": "dmz"}}]},
            *[
                {
                    "type": "vcd_nsxt_ipsec_vpn_tunnel",
                    "name": label,
                    "instances": [{"attributes": {"pre_shared_key": psk} if psk
                                   else {"name": label}}],
                }
                for label, psk in tunnels
            ],
        ],
    }


class TestFromTunnels:
    def test_builds_var_names_from_slugs(self):
        assert psk_vars_from_tunnels([
            {"slug": "ttk_crop91", "psk": "secret1"},
        ]) == {"psk_ttk_crop91": "secret1"}

    def test_skips_tunnel_without_psk(self):
        assert psk_vars_from_tunnels([{"slug": "a", "psk": None}]) == {}

    def test_empty_input(self):
        assert psk_vars_from_tunnels([]) == {}


class TestFromState:
    def test_extracts_keys(self):
        assert psk_vars_from_state(_state(("ttk_crop91", "secret1"))) == {
            "psk_ttk_crop91": "secret1"
        }

    def test_accepts_json_string(self):
        assert psk_vars_from_state(json.dumps(_state(("a", "k")))) == {"psk_a": "k"}

    def test_ignores_other_resource_types(self):
        out = psk_vars_from_state(_state(("a", "k")))
        assert list(out) == ["psk_a"]

    def test_tunnel_without_key_is_omitted_not_blank(self):
        """An empty pre_shared_key applies cleanly and never establishes."""
        assert psk_vars_from_state(_state(("a", None))) == {}

    def test_multiple_tunnels(self):
        out = psk_vars_from_state(_state(("a", "k1"), ("b", "k2")))
        assert out == {"psk_a": "k1", "psk_b": "k2"}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            psk_vars_from_state("{not json")

    def test_empty_state(self):
        assert psk_vars_from_state({"resources": []}) == {}

    def test_var_names_match_generator_slugs(self):
        """The state label is the terraform resource name, which the
        generator set from the tunnel slug — so both sources agree."""
        from_tunnels = psk_vars_from_tunnels([{"slug": "ttk_crop91", "psk": "k"}])
        from_state = psk_vars_from_state(_state(("ttk_crop91", "k")))
        assert set(from_tunnels) == set(from_state)
