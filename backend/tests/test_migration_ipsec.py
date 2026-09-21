"""Tests for IPsec normalization — NSX-V ipsec/config → canonical JSON.

The crypto values below are not invented: they are every distinct value
found across all 107 tunnels on the legacy VCD, collected before this
code was written. A value with no NSX-T equivalent (3DES) must surface
as an explicit refusal, never a silent default, because a tunnel built
on a guessed algorithm fails at 3am rather than at generation time.
"""

import pytest

from app.migration.normalizer import (
    NSXV_TO_NSXT,
    _normalize_ipsec,
    normalize_edge_snapshot,
)


# -----------------------------------------------------------------------
#  XML Fixtures
# -----------------------------------------------------------------------

def _site(
    name="site-1",
    enabled="true",
    local_ip="87.255.215.204",
    peer_ip="212.98.183.16",
    local_id=None,
    peer_id=None,
    local_subnets=("10.0.10.0/24",),
    peer_subnets=("192.168.14.0/23",),
    enc="aes256",
    digest="sha-256",
    dh="dh14",
    ike="ikev2",
    pfs="true",
    psk="RealPreSharedKey123",
    extra="",
):
    local_id = local_ip if local_id is None else local_id
    peer_id = peer_ip if peer_id is None else peer_id
    locals_xml = "".join(f"<subnet>{s}</subnet>" for s in local_subnets)
    peers_xml = "".join(f"<subnet>{s}</subnet>" for s in peer_subnets)
    return f"""
  <site>
    <name>{name}</name>
    <enabled>{enabled}</enabled>
    <localIp>{local_ip}</localIp>
    <localId>{local_id}</localId>
    <peerIp>{peer_ip}</peerIp>
    <peerId>{peer_id}</peerId>
    <localSubnets>{locals_xml}</localSubnets>
    <peerSubnets>{peers_xml}</peerSubnets>
    <encryptionAlgorithm>{enc}</encryptionAlgorithm>
    <digestAlgorithm>{digest}</digestAlgorithm>
    <dhGroup>{dh}</dhGroup>
    <ikeOption>{ike}</ikeOption>
    <enablePfs>{pfs}</enablePfs>
    <authenticationMode>psk</authenticationMode>
    <psk>{psk}</psk>
    {extra}
  </site>"""


def _ipsec(sites, enabled="true"):
    return f"""<ipsec>
  <enabled>{enabled}</enabled>
  <sites>{"".join(sites)}</sites>
</ipsec>"""


IPSEC_XML = _ipsec([_site()])


# -----------------------------------------------------------------------
#  Mapping table
# -----------------------------------------------------------------------


class TestMappingTable:
    """Every value observed on the real edges must be covered."""

    @pytest.mark.parametrize(
        "field,value,expected",
        [
            ("encryptionAlgorithm", "aes", "AES_128"),
            ("encryptionAlgorithm", "aes256", "AES_256"),
            ("digestAlgorithm", "sha1", "SHA1"),
            ("digestAlgorithm", "sha-256", "SHA2_256"),
            ("dhGroup", "dh2", "GROUP2"),
            ("dhGroup", "dh5", "GROUP5"),
            ("dhGroup", "dh14", "GROUP14"),
            ("dhGroup", "dh16", "GROUP16"),
            ("ikeVersion", "ikev1", "IKE_V1"),
            ("ikeVersion", "ikev2", "IKE_V2"),
            # Spelled with a hyphen on the wire. Assuming "ikeflex" would
            # have silently fallen through to a default.
            ("ikeVersion", "ike-flex", "IKE_FLEX"),
        ],
    )
    def test_observed_value_maps(self, field, value, expected):
        assert NSXV_TO_NSXT[field][value] == expected

    def test_3des_has_no_equivalent(self):
        """NSX-T dropped 3DES. There is nothing to map it to."""
        assert "3des" not in NSXV_TO_NSXT["encryptionAlgorithm"]


# -----------------------------------------------------------------------
#  _normalize_ipsec
# -----------------------------------------------------------------------


class TestNormalizeIpsec:
    def test_service_enabled_captured(self):
        result = _normalize_ipsec(IPSEC_XML)
        assert result["enabled"] is True

    def test_service_disabled_captured(self):
        result = _normalize_ipsec(_ipsec([_site()], enabled="false"))
        assert result["enabled"] is False

    def test_no_sites_yields_empty_list(self):
        assert _normalize_ipsec("<ipsec><enabled>false</enabled></ipsec>")["tunnels"] == []

    def test_tunnel_basics(self):
        t = _normalize_ipsec(IPSEC_XML)["tunnels"][0]
        assert t["name"] == "site-1"
        assert t["local_ip"] == "87.255.215.204"
        assert t["peer_ip"] == "212.98.183.16"
        assert t["local_networks"] == ["10.0.10.0/24"]
        assert t["remote_networks"] == ["192.168.14.0/23"]

    def test_crypto_is_translated_not_copied(self):
        t = _normalize_ipsec(IPSEC_XML)["tunnels"][0]
        assert t["encryption"] == "AES_256"
        assert t["digest"] == "SHA2_256"
        assert t["dh_group"] == "GROUP14"
        assert t["ike_version"] == "IKE_V2"
        assert t["pfs"] is True

    def test_psk_is_carried(self):
        t = _normalize_ipsec(IPSEC_XML)["tunnels"][0]
        assert t["psk"] == "RealPreSharedKey123"

    def test_disabled_tunnel_is_kept_not_skipped(self):
        """Operator decision: disabled tunnels migrate as-is."""
        t = _normalize_ipsec(_ipsec([_site(enabled="false")]))["tunnels"][0]
        assert t["enabled"] is False

    def test_multiple_subnets(self):
        xml = _ipsec([_site(
            local_subnets=("10.0.10.5/32", "10.0.10.11/32"),
            peer_subnets=("10.8.29.11/32", "10.130.0.120/29"),
        )])
        t = _normalize_ipsec(xml)["tunnels"][0]
        assert t["local_networks"] == ["10.0.10.5/32", "10.0.10.11/32"]
        assert t["remote_networks"] == ["10.8.29.11/32", "10.130.0.120/29"]


# -----------------------------------------------------------------------
#  Peer identity — the trap that costs hours to debug
# -----------------------------------------------------------------------


class TestRemoteId:
    def test_remote_id_omitted_when_same_as_peer_ip(self):
        """NSX-T defaults remote_id to the peer IP; saying it twice is noise."""
        t = _normalize_ipsec(IPSEC_XML)["tunnels"][0]
        assert t["remote_id"] is None

    def test_remote_id_set_when_peer_is_behind_nat(self):
        """Without this the tunnel fails phase 1 and the log blames auth."""
        xml = _ipsec([_site(peer_ip="212.98.183.16", peer_id="10.168.202.2")])
        t = _normalize_ipsec(xml)["tunnels"][0]
        assert t["remote_id"] == "10.168.202.2"

    def test_local_id_recorded_when_it_differs(self):
        xml = _ipsec([_site(local_ip="87.255.215.204", local_id="vpn.example.kz")])
        t = _normalize_ipsec(xml)["tunnels"][0]
        assert t["local_id"] == "vpn.example.kz"


# -----------------------------------------------------------------------
#  Refusals — loud, never a default
# -----------------------------------------------------------------------


class TestUnsupported:
    def test_3des_tunnel_is_flagged_not_translated(self):
        t = _normalize_ipsec(_ipsec([_site(enc="3des")]))["tunnels"][0]
        assert t["encryption"] is None
        assert any("3des" in u for u in t["unsupported"])

    def test_unknown_algorithm_is_flagged(self):
        t = _normalize_ipsec(_ipsec([_site(dh="dh99")]))["tunnels"][0]
        assert t["dh_group"] is None
        assert any("dh99" in u for u in t["unsupported"])

    def test_supported_tunnel_has_no_unsupported_entries(self):
        assert _normalize_ipsec(IPSEC_XML)["tunnels"][0]["unsupported"] == []

    def test_peer_any_is_flagged(self):
        """NSX-T needs a concrete remote address."""
        t = _normalize_ipsec(_ipsec([_site(peer_ip="any", peer_id="any")]))["tunnels"][0]
        assert any("peer" in u.lower() for u in t["unsupported"])

    def test_empty_remote_networks_is_flagged(self):
        """NSX-T reads an empty remote_networks as 0.0.0.0/0."""
        t = _normalize_ipsec(_ipsec([_site(peer_subnets=())]))["tunnels"][0]
        assert any("remote" in u.lower() for u in t["unsupported"])

    def test_migratable_flag_reflects_unsupported(self):
        good = _normalize_ipsec(IPSEC_XML)["tunnels"][0]
        bad = _normalize_ipsec(_ipsec([_site(enc="3des")]))["tunnels"][0]
        assert good["migratable"] is True
        assert bad["migratable"] is False


# -----------------------------------------------------------------------
#  Snapshot integration
# -----------------------------------------------------------------------


class TestSnapshotIntegration:
    """ipsec_config.xml is optional so snapshots taken before IPsec support
    still normalize."""

    def _snapshot(self, **extra):
        from tests.test_migration_normalizer import (
            EDGE_METADATA_XML,
            FIREWALL_XML,
            NAT_XML,
            ROUTING_XML,
        )
        base = {
            "edge_metadata.xml": EDGE_METADATA_XML,
            "firewall_config.xml": FIREWALL_XML,
            "nat_config.xml": NAT_XML,
            "routing_config.xml": ROUTING_XML,
        }
        base.update(extra)
        return base

    def test_snapshot_without_ipsec_still_works(self):
        result = normalize_edge_snapshot(self._snapshot())
        assert result["ipsec"]["tunnels"] == []

    def test_snapshot_with_ipsec_includes_tunnels(self):
        result = normalize_edge_snapshot(
            self._snapshot(**{"ipsec_config.xml": IPSEC_XML})
        )
        assert len(result["ipsec"]["tunnels"]) == 1
        assert result["ipsec"]["tunnels"][0]["encryption"] == "AES_256"
