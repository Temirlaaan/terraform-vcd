"""Tests for IPsec HCL generation — canonical JSON → vcd_nsxt_ipsec_vpn_tunnel.

Two rules drive most of these: a pre-shared key must never appear in the
rendered HCL, and a tunnel must never come up on its own. Cutover is a
per-tunnel decision the operator makes while watching the SA, so every
tunnel is rendered disabled.
"""

import re

import pytest

from app.migration.generator import MigrationHCLGenerator


TARGET = {
    "target_org": "CLT_ADAMANT_SYSTEMS",
    "target_vdc": "clt_vdc",
    "target_edge_id": "urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271",
    "target_vdc_id": "urn:vcloud:vdc:11111111-2222-3333-4444-555555555555",
}


def _tunnel(**over):
    base = {
        "name": "TTK - Crop91",
        "enabled": True,
        "local_ip": "87.255.215.204",
        "peer_ip": "212.98.183.16",
        "local_id": None,
        "remote_id": None,
        "local_networks": ["10.0.10.0/24"],
        "remote_networks": ["192.168.14.0/23"],
        "encryption": "AES_256",
        "digest": "SHA2_256",
        "dh_group": "GROUP14",
        "ike_version": "IKE_V2",
        "pfs": True,
        "psk": "TopSecretKey12345",
        "unsupported": [],
        "migratable": True,
    }
    base.update(over)
    return base


def _normalized(tunnels):
    return {
        "firewall": {"rules": []},
        "nat": {"rules": [], "required_app_port_profiles": []},
        "routing": {"static_routes": []},
        "edge": {"name": "src-edge", "interfaces": []},
        "ipsec": {"enabled": True, "tunnels": tunnels},
    }


def _render(tunnels):
    return MigrationHCLGenerator().generate(_normalized(tunnels), **TARGET)


def _tunnel_block(hcl: str) -> str:
    """Just the ipsec tunnel resource, without the NAT rules beside it."""
    match = re.search(
        r'resource "vcd_nsxt_ipsec_vpn_tunnel".*?\n\}', hcl, re.DOTALL
    )
    return match.group(0) if match else ""


# -----------------------------------------------------------------------
#  Secrets
# -----------------------------------------------------------------------


class TestPskNeverInHcl:
    def test_psk_value_absent_from_rendered_hcl(self):
        """The project rule: secrets reach terraform through TF_VAR_*, never
        through a rendered file that gets stored and previewed in a browser."""
        hcl = _render([_tunnel(psk="TopSecretKey12345")])
        assert "TopSecretKey12345" not in hcl

    def test_psk_bound_to_a_variable(self):
        hcl = _render([_tunnel()])
        assert re.search(r"pre_shared_key\s*=\s*var\.psk_\w+", hcl)

    def test_psk_variable_is_declared_and_sensitive(self):
        hcl = _render([_tunnel()])
        match = re.search(r"pre_shared_key\s*=\s*var\.(psk_\w+)", hcl)
        assert match
        var_name = match.group(1)
        decl = re.search(
            rf'variable\s+"{var_name}"\s*\{{(.*?)\}}', hcl, re.DOTALL
        )
        assert decl, f"variable {var_name} is not declared"
        assert re.search(r"sensitive\s*=\s*true", decl.group(1))

    def test_no_psk_variable_has_a_default(self):
        """A default would put the secret back into the HCL."""
        hcl = _render([_tunnel()])
        for block in re.findall(r'variable\s+"psk_\w+"\s*\{(.*?)\}', hcl, re.DOTALL):
            assert "default" not in block


# -----------------------------------------------------------------------
#  Cutover safety
# -----------------------------------------------------------------------


class TestAlwaysDisabled:
    def test_enabled_tunnel_is_rendered_disabled(self):
        # Scoped to the tunnel block: the NO_SNAT companions alongside it
        # are enabled on purpose.
        block = _tunnel_block(_render([_tunnel(enabled=True)]))
        assert re.search(r"\benabled\s*=\s*false", block)
        assert not re.search(r"(?<![\w_])enabled\s*=\s*true", block)

    def test_disabled_tunnel_is_also_rendered_disabled(self):
        block = _tunnel_block(_render([_tunnel(enabled=False)]))
        assert re.search(r"\benabled\s*=\s*false", block)


# -----------------------------------------------------------------------
#  Tunnel body
# -----------------------------------------------------------------------


class TestTunnelRendering:
    def test_resource_type_and_endpoints(self):
        hcl = _render([_tunnel()])
        assert 'resource "vcd_nsxt_ipsec_vpn_tunnel"' in hcl
        assert re.search(r'local_ip_address\s*=\s*"87\.255\.215\.204"', hcl)
        assert re.search(r'remote_ip_address\s*=\s*"212\.98\.183\.16"', hcl)

    def test_networks_rendered_as_lists(self):
        hcl = _render([_tunnel(
            local_networks=["10.0.10.5/32", "10.0.10.11/32"],
            remote_networks=["10.8.29.11/32"],
        )])
        assert '"10.0.10.5/32", "10.0.10.11/32"' in hcl
        assert '"10.8.29.11/32"' in hcl

    def test_security_profile_is_always_emitted(self):
        """NSX-T defaults differ from NSX-V, so a tunnel that relies on them
        may never establish. Everything is stated explicitly."""
        hcl = _render([_tunnel()])
        assert "security_profile_customization" in hcl
        assert re.search(r'ike_version\s*=\s*"IKE_V2"', hcl)
        assert "AES_256" in hcl
        assert "SHA2_256" in hcl
        assert "GROUP14" in hcl

    def test_phase1_and_phase2_both_set(self):
        """NSX-V carries one set of parameters; NSX-T splits them."""
        hcl = _render([_tunnel()])
        assert "ike_encryption_algorithms" in hcl
        assert "tunnel_encryption_algorithms" in hcl

    def test_pfs_reflected(self):
        assert re.search(r"tunnel_pfs_enabled\s*=\s*true", _render([_tunnel(pfs=True)]))
        assert re.search(r"tunnel_pfs_enabled\s*=\s*false", _render([_tunnel(pfs=False)]))

    def test_unique_resource_names_for_duplicate_tunnel_names(self):
        hcl = _render([_tunnel(name="vpn"), _tunnel(name="vpn")])
        labels = re.findall(r'resource "vcd_nsxt_ipsec_vpn_tunnel" "(\w+)"', hcl)
        assert len(labels) == 2
        assert len(set(labels)) == 2

    def test_resource_name_is_a_valid_identifier(self):
        hcl = _render([_tunnel(name="172.158.1.0 to inet")])
        for label in re.findall(r'resource "vcd_nsxt_ipsec_vpn_tunnel" "([^"]+)"', hcl):
            assert re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", label)


# -----------------------------------------------------------------------
#  Peer identity
# -----------------------------------------------------------------------


class TestRemoteId:
    def test_remote_id_emitted_when_present(self):
        hcl = _render([_tunnel(remote_id="10.168.202.2")])
        assert 'remote_id' in hcl and "10.168.202.2" in hcl

    def test_remote_id_omitted_when_none(self):
        hcl = _render([_tunnel(remote_id=None)])
        assert "remote_id" not in hcl


# -----------------------------------------------------------------------
#  Refusals
# -----------------------------------------------------------------------


class TestUnsupportedTunnels:
    def test_unmigratable_tunnel_is_not_rendered(self):
        hcl = _render([_tunnel(
            name="legacy-3des",
            encryption=None,
            unsupported=["encryptionAlgorithm=3des has no NSX-T equivalent"],
            migratable=False,
        )])
        assert 'resource "vcd_nsxt_ipsec_vpn_tunnel"' not in hcl

    def test_unmigratable_tunnel_is_explained_in_a_comment(self):
        """Silence would read as 'this edge had no VPN'."""
        hcl = _render([_tunnel(
            name="legacy-3des",
            unsupported=["encryptionAlgorithm=3des has no NSX-T equivalent"],
            migratable=False,
        )])
        assert "legacy-3des" in hcl
        assert "3des" in hcl

    def test_mixed_batch_renders_only_the_good_ones(self):
        hcl = _render([
            _tunnel(name="good"),
            _tunnel(name="bad", unsupported=["nope"], migratable=False),
        ])
        labels = re.findall(r'resource "vcd_nsxt_ipsec_vpn_tunnel" "(\w+)"', hcl)
        assert len(labels) == 1

    def test_no_tunnels_renders_no_ipsec_section(self):
        hcl = _render([])
        assert "vcd_nsxt_ipsec_vpn_tunnel" not in hcl
        assert not re.search(r'variable\s+"psk_', hcl)


# -----------------------------------------------------------------------
#  NO_SNAT companions
# -----------------------------------------------------------------------


class TestNoSnat:
    """Without these, VPN traffic leaves through the general internet SNAT
    rule and never enters the tunnel. NSX-V did not need them stated; NSX-T
    evaluates NAT for this traffic and does."""

    def test_one_rule_per_network_pair(self):
        hcl = _render([_tunnel(
            local_networks=["10.0.10.0/24"],
            remote_networks=["192.168.14.0/23"],
        )])
        rules = re.findall(r'resource "vcd_nsxt_nat_rule" "(\w+)"', hcl)
        assert len(rules) == 1

    def test_cross_product_of_networks(self):
        """Each NAT rule carries one internal and one destination CIDR, so a
        tunnel with two local and two remote networks needs four."""
        hcl = _render([_tunnel(
            local_networks=["10.0.10.5/32", "10.0.10.11/32"],
            remote_networks=["10.8.29.11/32", "10.130.0.120/29"],
        )])
        assert len(re.findall(r'resource "vcd_nsxt_nat_rule"', hcl)) == 4

    def test_rule_shape(self):
        hcl = _render([_tunnel(
            local_networks=["10.0.10.0/24"],
            remote_networks=["192.168.14.0/23"],
        )])
        block = re.search(
            r'resource "vcd_nsxt_nat_rule".*?\n\}', hcl, re.DOTALL
        ).group(0)
        assert 'rule_type                = "NO_SNAT"' in block or "NO_SNAT" in block
        assert '"10.0.10.0/24"' in block
        assert '"192.168.14.0/23"' in block

    def test_rules_are_enabled(self):
        """Harmless while the tunnel is down — nothing routes to the remote
        networks — and required the moment it comes up."""
        hcl = _render([_tunnel()])
        block = re.search(
            r'resource "vcd_nsxt_nat_rule".*?\n\}', hcl, re.DOTALL
        ).group(0)
        assert re.search(r"\benabled\s*=\s*true", block)

    def test_priority_beats_a_general_snat(self):
        """Lower number wins in NSX-T. A default-priority NO_SNAT would lose
        to an existing internet SNAT rule and do nothing."""
        hcl = _render([_tunnel()])
        match = re.search(r"priority\s*=\s*(\d+)", hcl)
        assert match, "no priority set"
        assert int(match.group(1)) < 100

    def test_no_rules_for_skipped_tunnels(self):
        hcl = _render([_tunnel(migratable=False, unsupported=["nope"])])
        assert "vcd_nsxt_nat_rule" not in hcl

    def test_resource_names_are_valid_identifiers(self):
        hcl = _render([_tunnel(name="172.158.1.0 to inet")])
        for label in re.findall(r'resource "vcd_nsxt_nat_rule" "([^"]+)"', hcl):
            assert re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", label)

    def test_unique_names_across_tunnels(self):
        hcl = _render([_tunnel(name="a"), _tunnel(name="b")])
        labels = re.findall(r'resource "vcd_nsxt_nat_rule" "(\w+)"', hcl)
        assert len(labels) == len(set(labels))
