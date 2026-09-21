"""Tests for overriding the tunnel's local address.

The source address is often not allocated on the destination yet, which
fails the apply. Overriding it lets the whole pipeline be validated on a
free address — at the cost of a tunnel that cannot establish, since the
peer still expects the original.
"""

import pytest

from app.api.routes.ipsec_migration import _apply_local_ip_map, _local_ips


def _t(name="t1", local_ip="87.255.215.204"):
    return {"name": name, "local_ip": local_ip, "migratable": True}


class TestCollect:
    def test_distinct_addresses_in_order(self):
        assert _local_ips([_t(local_ip="1.1.1.1"), _t(local_ip="2.2.2.2")]) == [
            "1.1.1.1",
            "2.2.2.2",
        ]

    def test_deduplicates(self):
        """Every tunnel on an edge usually shares one local address."""
        assert _local_ips([_t(), _t(), _t()]) == ["87.255.215.204"]

    def test_ignores_empty(self):
        assert _local_ips([_t(local_ip="")]) == []


class TestApply:
    def test_replaces_mapped_address(self):
        out = _apply_local_ip_map(
            [_t(local_ip="87.255.215.204")], {"87.255.215.204": "87.255.215.99"}
        )
        assert out[0]["local_ip"] == "87.255.215.99"

    def test_leaves_unmapped_alone(self):
        out = _apply_local_ip_map([_t(local_ip="1.1.1.1")], {"2.2.2.2": "3.3.3.3"})
        assert out[0]["local_ip"] == "1.1.1.1"

    def test_empty_map_is_a_no_op(self):
        tunnels = [_t()]
        assert _apply_local_ip_map(tunnels, {}) == tunnels

    def test_does_not_mutate_the_input(self):
        tunnels = [_t(local_ip="1.1.1.1")]
        _apply_local_ip_map(tunnels, {"1.1.1.1": "2.2.2.2"})
        assert tunnels[0]["local_ip"] == "1.1.1.1"

    def test_rejects_a_non_address(self):
        with pytest.raises(ValueError):
            _apply_local_ip_map([_t()], {"87.255.215.204": "not-an-ip"})

    def test_rejects_a_non_address_key(self):
        with pytest.raises(ValueError):
            _apply_local_ip_map([_t()], {"nonsense": "1.1.1.1"})
