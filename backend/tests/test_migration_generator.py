"""Tests for app.migration.generator — canonical JSON → HCL rendering."""

import pytest

from app.migration.generator import (
    MigrationHCLGenerator,
    _collect_firewall_app_port_profiles,
    _collect_ip_sets,
    _enrich_nat_rules,
    _merge_app_port_profiles,
    _netmask_to_cidr,
    _resolve_internal_networks,
)
from app.migration.normalizer import normalize_edge_snapshot

# Reuse the same XML fixtures from normalizer tests
from tests.test_migration_normalizer import (
    EDGE_METADATA_XML,
    FIREWALL_XML,
    NAT_XML,
    ROUTING_XML,
)


# -----------------------------------------------------------------------
#  Fixture: normalized JSON from the test XML data
# -----------------------------------------------------------------------


@pytest.fixture
def normalized():
    """Full normalized snapshot from test XML fixtures."""
    return normalize_edge_snapshot({
        "edge_metadata.xml": EDGE_METADATA_XML,
        "firewall_config.xml": FIREWALL_XML,
        "nat_config.xml": NAT_XML,
        "routing_config.xml": ROUTING_XML,
    })


@pytest.fixture
def generator():
    return MigrationHCLGenerator()


@pytest.fixture
def full_hcl(generator, normalized):
    """Full HCL output from the generator."""
    return generator.generate(
        normalized,
        target_org="TestOrg",
        target_vdc="TestVDC",
        target_edge_id="urn:vcloud:gateway:abc-123",
    )


# -----------------------------------------------------------------------
#  Variables template
# -----------------------------------------------------------------------


class TestMigrationHCLGeneratorVariables:
    def test_provider_variables_rendered(self, full_hcl):
        assert 'variable "vcd_url"' in full_hcl
        assert 'variable "vcd_user"' in full_hcl
        assert 'variable "vcd_password"' in full_hcl

    def test_target_org_default_value(self, full_hcl):
        assert 'default = "TestOrg"' in full_hcl

    def test_target_vdc_default_value(self, full_hcl):
        assert 'default = "TestVDC"' in full_hcl

    def test_target_edge_id_default_value(self, full_hcl):
        assert 'default = "urn:vcloud:gateway:abc-123"' in full_hcl

    def test_sensitive_variables(self, full_hcl):
        # vcd_user and vcd_password should be sensitive
        lines = full_hcl.split("\n")
        for i, line in enumerate(lines):
            if 'variable "vcd_user"' in line or 'variable "vcd_password"' in line:
                # Check the block contains sensitive = true
                block = "\n".join(lines[i:i+5])
                assert "sensitive" in block

    def test_no_literal_credentials(self, full_hcl):
        """No hardcoded credential values should appear in HCL."""
        for line in full_hcl.split("\n"):
            if "password" in line.lower() and "=" in line:
                assert "var." in line or "sensitive" in line or "string" in line or "variable" in line, (
                    f"Possible credential leak: {line}"
                )

    def test_hcl_escape_in_defaults(self, generator, normalized):
        """Org name with special chars should be escaped."""
        hcl = generator.generate(
            normalized,
            target_org='Org "Special"',
            target_vdc="TestVDC",
            target_edge_id="urn:test",
        )
        assert 'Org \\"Special\\"' in hcl


# -----------------------------------------------------------------------
#  IP Sets
# -----------------------------------------------------------------------


class TestCollectIpSets:
    def test_ip_set_created_for_source_ips(self, normalized):
        ip_sets = _collect_ip_sets(normalized["firewall"]["rules"])
        # Rule 135393 has 3 source IPs
        src_sets = [s for s in ip_sets if "10.121.24.3/32" in s["ip_addresses"]]
        assert len(src_sets) == 1
        assert len(src_sets[0]["ip_addresses"]) == 3

    def test_ip_set_created_for_destination_ips(self, normalized):
        ip_sets = _collect_ip_sets(normalized["firewall"]["rules"])
        dst_sets = [s for s in ip_sets if "192.168.1.0/24" in s["ip_addresses"]]
        assert len(dst_sets) == 1

    def test_no_ip_set_for_empty_ips(self, normalized):
        ip_sets = _collect_ip_sets(normalized["firewall"]["rules"])
        for ip_set in ip_sets:
            assert len(ip_set["ip_addresses"]) > 0

    def test_no_ip_set_for_system_rules(self, normalized):
        ip_sets = _collect_ip_sets(normalized["firewall"]["rules"])
        # default_policy rule (131076) should not generate IP sets
        for ip_set in ip_sets:
            for rule_ref in ip_set["used_by"]:
                assert rule_ref["rule_id"] != "131076"

    def test_dedup_identical_ip_sets(self):
        """Rules with the same IP list should share one IP set."""
        rules = [
            {
                "original_id": "1",
                "is_system": False,
                "source": {"ip_addresses": ["10.0.0.1", "10.0.0.2"], "exclude": False},
                "destination": {"ip_addresses": [], "exclude": False},
            },
            {
                "original_id": "2",
                "is_system": False,
                "source": {"ip_addresses": ["10.0.0.1", "10.0.0.2"], "exclude": False},
                "destination": {"ip_addresses": [], "exclude": False},
            },
        ]
        ip_sets = _collect_ip_sets(rules)
        # Both rules use same source IPs → one IP set, used by 2 rules
        src_sets = [s for s in ip_sets if "10.0.0.1" in s["ip_addresses"]]
        assert len(src_sets) == 1
        assert len(src_sets[0]["used_by"]) == 2

    def test_ip_set_name_is_stable_hash(self):
        """IP set name should be based on hash of sorted IPs."""
        rules = [
            {
                "original_id": "1",
                "is_system": False,
                "source": {"ip_addresses": ["10.0.0.2", "10.0.0.1"], "exclude": False},
                "destination": {"ip_addresses": [], "exclude": False},
            },
        ]
        ip_sets = _collect_ip_sets(rules)
        assert len(ip_sets) == 1
        assert ip_sets[0]["name"].startswith("ipset_")

    def test_different_order_same_hash(self):
        """IPs in different order should produce the same IP set."""
        rules = [
            {
                "original_id": "1",
                "is_system": False,
                "source": {"ip_addresses": ["10.0.0.2", "10.0.0.1"], "exclude": False},
                "destination": {"ip_addresses": [], "exclude": False},
            },
            {
                "original_id": "2",
                "is_system": False,
                "source": {"ip_addresses": ["10.0.0.1", "10.0.0.2"], "exclude": False},
                "destination": {"ip_addresses": [], "exclude": False},
            },
        ]
        ip_sets = _collect_ip_sets(rules)
        src_sets = [s for s in ip_sets if "10.0.0.1" in s["ip_addresses"]]
        assert len(src_sets) == 1
        assert len(src_sets[0]["used_by"]) == 2


class TestMigrationHCLGeneratorIpSets:
    def test_ip_set_resource_rendered(self, full_hcl):
        assert 'resource "vcd_nsxt_ip_set"' in full_hcl

    def test_ip_set_has_edge_gateway_id(self, full_hcl):
        lines = full_hcl.split("\n")
        in_ip_set = False
        found = False
        for line in lines:
            if 'resource "vcd_nsxt_ip_set"' in line:
                in_ip_set = True
            if in_ip_set and "edge_gateway_id" in line:
                assert "var.target_edge_id" in line
                found = True
                break
        assert found

    def test_ip_set_ip_addresses_rendered(self, full_hcl):
        # Should contain the actual IPs from rule 135393
        assert "10.121.24.3/32" in full_hcl
        assert "10.121.44.0/24" in full_hcl
        assert "10.121.43.0/24" in full_hcl


# -----------------------------------------------------------------------
#  App Port Profiles
# -----------------------------------------------------------------------


class TestMigrationHCLGeneratorAppPortProfiles:
    def test_system_profile_as_data_source(self, full_hcl):
        assert 'data "vcd_nsxt_app_port_profile"' in full_hcl
        assert 'scope = "SYSTEM"' in full_hcl

    def test_custom_profile_as_resource(self, full_hcl):
        assert 'resource "vcd_nsxt_app_port_profile"' in full_hcl

    def test_custom_profile_scope_tenant(self, full_hcl):
        assert 'scope       = "TENANT"' in full_hcl

    def test_custom_profile_description_contains_rule_ids(self, full_hcl):
        # The custom UDP profile is used by rule 233621
        assert "233621" in full_hcl

    def test_system_profile_name_https(self, full_hcl):
        assert '"HTTPS"' in full_hcl

    def test_no_profiles_when_empty(self, generator):
        normalized = {
            "firewall": {"enabled": True, "default_action_source": "ALLOW",
                         "default_action_target": None, "rules": []},
            "nat": {"enabled": True, "rules": [], "required_app_port_profiles": []},
            "routing": {"static_routes": []},
            "source": {"edge_name": "test", "backing_type": "NSXV_BACKED", "snapshot_at": ""},
            "edge": {"name": "test", "interfaces": [], "backing_type": "NSXV_BACKED"},
            "schema_version": 1,
        }
        hcl = generator.generate(normalized, "Org", "VDC", "urn:test")
        assert "vcd_nsxt_app_port_profile" not in hcl


# -----------------------------------------------------------------------
#  Firewall
# -----------------------------------------------------------------------


class TestMigrationHCLGeneratorFirewall:
    def test_firewall_resource_rendered(self, full_hcl):
        assert 'resource "vcd_nsxt_firewall"' in full_hcl

    def test_user_rules_included(self, full_hcl):
        # Rule 135393 (user) should appear
        assert "migrated_rule_135393" in full_hcl

    def test_default_policy_rules_excluded(self, full_hcl):
        """default_policy rules should NOT appear in firewall rules."""
        lines = full_hcl.split("\n")
        in_firewall = False
        for line in lines:
            if 'resource "vcd_nsxt_firewall"' in line:
                in_firewall = True
            if in_firewall and "131076" in line:
                pytest.fail("Default policy rule 131076 should not appear in firewall HCL")

    def test_internal_high_rules_included(self, full_hcl):
        """internal_high rules are user rules with a priority, not system rules."""
        assert "131073" in full_hcl

    def test_source_ids_reference_ip_set(self, full_hcl):
        # Rule 135393 has source IPs → should reference IP set
        assert "vcd_nsxt_ip_set" in full_hcl

    def test_action_allow_rendered(self, full_hcl):
        assert "ALLOW" in full_hcl

    def test_action_drop_rendered(self, full_hcl):
        assert "DROP" in full_hcl

    def test_disabled_rule_included(self, full_hcl):
        # Rule 131075 is disabled but user type → should be in HCL with enabled=false
        assert "migrated_131075_disabled_rule" in full_hcl

    def test_no_firewall_when_no_user_rules(self, generator):
        """No firewall block when all rules are system rules."""
        normalized = {
            "firewall": {
                "enabled": True,
                "default_action_source": "ALLOW",
                "default_action_target": None,
                "rules": [
                    {"original_id": "1", "name": "sys", "rule_type": "default_policy",
                     "is_system": True, "enabled": True, "action": "ALLOW",
                     "logging": False, "source": {"ip_addresses": [], "grouping_object_ids": [],
                     "vnic_group_ids": [], "exclude": False},
                     "destination": {"ip_addresses": [], "grouping_object_ids": [],
                     "vnic_group_ids": [], "exclude": False}, "application": []},
                ],
            },
            "nat": {"enabled": True, "rules": [], "required_app_port_profiles": []},
            "routing": {"static_routes": []},
            "source": {"edge_name": "test", "backing_type": "NSXV_BACKED", "snapshot_at": ""},
            "edge": {"name": "test", "interfaces": [], "backing_type": "NSXV_BACKED"},
            "schema_version": 1,
        }
        hcl = generator.generate(normalized, "Org", "VDC", "urn:test")
        assert "vcd_nsxt_firewall" not in hcl


# -----------------------------------------------------------------------
#  NAT
# -----------------------------------------------------------------------


class TestEnrichNatRules:
    def test_system_profile_flagged(self, normalized):
        enriched = _enrich_nat_rules(normalized["nat"])
        rule = next(r for r in enriched["rules"] if r["original_id"] == "200825")
        assert rule["is_system_profile"] is True

    def test_custom_profile_flagged(self, normalized):
        enriched = _enrich_nat_rules(normalized["nat"])
        rule = next(r for r in enriched["rules"] if r["original_id"] == "233621")
        assert rule["is_system_profile"] is False

    def test_no_profile_rule_not_flagged(self, normalized):
        enriched = _enrich_nat_rules(normalized["nat"])
        rule = next(r for r in enriched["rules"] if r["original_id"] == "200826")
        assert rule["is_system_profile"] is False


class TestMigrationHCLGeneratorNat:
    def test_dnat_rule_rendered(self, full_hcl):
        assert 'resource "vcd_nsxt_nat_rule"' in full_hcl

    def test_dnat_rule_type(self, full_hcl):
        assert 'rule_type         = "DNAT"' in full_hcl

    def test_snat_rule_type(self, full_hcl):
        assert 'rule_type         = "SNAT"' in full_hcl

    def test_dnat_external_port_rendered(self, full_hcl):
        assert "dnat_external_port" in full_hcl

    def test_snat_no_external_port(self, full_hcl):
        """SNAT rules should not have dnat_external_port."""
        lines = full_hcl.split("\n")
        in_snat = False
        for line in lines:
            if 'rule_type         = "SNAT"' in line:
                in_snat = True
            if in_snat and "dnat_external_port" in line:
                pytest.fail("SNAT rule should not have dnat_external_port")
            if in_snat and line.strip() == "}":
                break

    def test_app_port_profile_system_reference(self, full_hcl):
        assert "data.vcd_nsxt_app_port_profile." in full_hcl

    def test_app_port_profile_custom_reference(self, full_hcl):
        # udp_9000-10999 is custom — no "resource." prefix in HCL2
        assert "vcd_nsxt_app_port_profile." in full_hcl
        # Ensure invalid "resource." prefix is NOT used
        assert "resource.vcd_nsxt_app_port_profile." not in full_hcl

    def test_no_app_port_profile_for_any_protocol(self, full_hcl):
        """SNAT rule with protocol=any should not have app_port_profile_id."""
        lines = full_hcl.split("\n")
        in_snat_block = False
        for line in lines:
            if "rule_200826" in line:
                in_snat_block = True
            if in_snat_block and "app_port_profile_id" in line:
                pytest.fail("SNAT with any protocol should not have app_port_profile_id")
            if in_snat_block and line.strip() == "}":
                break

    def test_rule_description_escaped(self, generator, normalized):
        """Description with quotes must be escaped."""
        # Modify a rule description to include quotes
        nat = normalized["nat"]
        nat["rules"][0]["description"] = 'SSH "admin"'
        hcl = generator.generate(
            normalized, "Org", "VDC", "urn:test",
        )
        assert 'SSH \\"admin\\"' in hcl

    def test_external_address_dnat(self, full_hcl):
        # DNAT: external = original_address
        assert 'external_address  = "37.208.43.38"' in full_hcl

    def test_internal_address_dnat(self, full_hcl):
        # DNAT: internal = translated_address
        assert 'internal_address  = "10.10.0.19"' in full_hcl


# -----------------------------------------------------------------------
#  Static Routes
# -----------------------------------------------------------------------


class TestMigrationHCLGeneratorStaticRoutes:
    def test_static_route_rendered(self, full_hcl):
        assert 'resource "vcd_nsxt_edgegateway_static_route"' in full_hcl

    def test_route_numbering_via_loop_index(self, full_hcl):
        assert "route_1" in full_hcl
        assert "route_2" in full_hcl

    def test_next_hop_rendered(self, full_hcl):
        assert "172.24.0.253" in full_hcl
        assert "172.24.0.254" in full_hcl

    def test_admin_distance_rendered(self, full_hcl):
        assert "admin_distance = 1" in full_hcl

    def test_network_cidr_rendered(self, full_hcl):
        assert "10.121.42.0/24" in full_hcl
        assert "10.121.43.0/24" in full_hcl

    def test_description_escaped(self, generator, normalized):
        normalized["routing"]["static_routes"][0]["description"] = 'Route "main"'
        hcl = generator.generate(normalized, "Org", "VDC", "urn:test")
        assert 'Route \\"main\\"' in hcl

    def test_empty_routes_no_output(self, generator):
        normalized = {
            "firewall": {"enabled": True, "default_action_source": "ALLOW",
                         "default_action_target": None, "rules": []},
            "nat": {"enabled": True, "rules": [], "required_app_port_profiles": []},
            "routing": {"static_routes": []},
            "source": {"edge_name": "test", "backing_type": "NSXV_BACKED", "snapshot_at": ""},
            "edge": {"name": "test", "interfaces": [], "backing_type": "NSXV_BACKED"},
            "schema_version": 1,
        }
        hcl = generator.generate(normalized, "Org", "VDC", "urn:test")
        assert "vcd_nsxt_edgegateway_static_route" not in hcl


# -----------------------------------------------------------------------
#  Internal vnic_group_ids resolution
# -----------------------------------------------------------------------


class TestInternalVnicResolution:
    def test_netmask_to_cidr(self):
        assert _netmask_to_cidr("10.10.0.1", "255.255.255.0") == "10.10.0.0/24"
        assert _netmask_to_cidr("172.16.5.1", "255.255.0.0") == "172.16.0.0/16"

    def test_resolve_internal_networks(self):
        edge_meta = {
            "interfaces": [
                {"type": "uplink", "name": "Internet", "subnets": [
                    {"gateway": "37.208.43.1", "netmask": "255.255.255.0", "ip_address": "37.208.43.38"},
                ]},
                {"type": "internal", "name": "Internal-Net", "subnets": [
                    {"gateway": "10.10.0.1", "netmask": "255.255.255.0", "ip_address": "10.10.0.1"},
                ]},
            ],
        }
        cidrs = _resolve_internal_networks(edge_meta)
        assert cidrs == ["10.10.0.0/24"]

    def test_collect_ip_sets_resolves_internal(self):
        edge_meta = {
            "interfaces": [
                {"type": "internal", "name": "Net1", "subnets": [
                    {"gateway": "10.10.0.1", "netmask": "255.255.255.0"},
                ]},
            ],
        }
        rules = [
            {
                "original_id": "100",
                "is_system": False,
                "source": {
                    "ip_addresses": [],
                    "vnic_group_ids": ["internal"],
                    "grouping_object_ids": [],
                    "exclude": False,
                },
                "destination": {
                    "ip_addresses": [],
                    "vnic_group_ids": [],
                    "grouping_object_ids": [],
                    "exclude": False,
                },
                "application": [],
            },
        ]
        ip_sets = _collect_ip_sets(rules, edge_meta=edge_meta)
        assert len(ip_sets) == 1
        assert "10.10.0.0/24" in ip_sets[0]["ip_addresses"]
        assert ip_sets[0]["display_name"] == "ipset_internal"

    def test_internal_vnic_in_full_hcl(self, full_hcl):
        """Rule 135500 uses vnicGroupId=internal → should produce IP set with 10.10.0.0/24."""
        assert "10.10.0.0/24" in full_hcl

    def test_unsupported_vnic_logs_warning(self, caplog):
        rules = [
            {
                "original_id": "200",
                "is_system": False,
                "source": {
                    "ip_addresses": [],
                    "vnic_group_ids": ["external"],
                    "grouping_object_ids": [],
                    "exclude": False,
                },
                "destination": {
                    "ip_addresses": [],
                    "vnic_group_ids": [],
                    "grouping_object_ids": [],
                    "exclude": False,
                },
                "application": [],
            },
        ]
        import logging
        with caplog.at_level(logging.WARNING):
            ip_sets = _collect_ip_sets(rules, edge_meta={"interfaces": []})
        assert "unsupported vnicGroupId=external" in caplog.text
        assert len(ip_sets) == 0


# -----------------------------------------------------------------------
#  Firewall app port profiles
# -----------------------------------------------------------------------


class TestFirewallAppPortProfiles:
    def test_collect_profiles_from_firewall_rule(self):
        rules = [
            {
                "original_id": "1",
                "is_system": False,
                "application": [{"protocol": "tcp", "port": "443"}],
            },
        ]
        profiles, rule_map = _collect_firewall_app_port_profiles(rules)
        assert len(profiles) == 1
        assert profiles[0]["key"] == "tcp_443"
        assert profiles[0]["is_system_defined"] is True
        assert profiles[0]["system_defined_name"] == "HTTPS"
        assert rule_map == {"1": ["tcp_443"]}

    def test_multi_service_rule_produces_multiple_keys(self):
        rules = [
            {
                "original_id": "1",
                "is_system": False,
                "application": [
                    {"protocol": "tcp", "port": "80"},
                    {"protocol": "tcp", "port": "443"},
                ],
            },
        ]
        profiles, rule_map = _collect_firewall_app_port_profiles(rules)
        assert len(profiles) == 2
        assert len(rule_map["1"]) == 2
        assert "tcp_80" in rule_map["1"]
        assert "tcp_443" in rule_map["1"]

    def test_icmp_protocol_mapped(self):
        rules = [
            {
                "original_id": "1",
                "is_system": False,
                "application": [{"protocol": "icmp"}],
            },
        ]
        profiles, _ = _collect_firewall_app_port_profiles(rules)
        assert len(profiles) == 1
        assert profiles[0]["protocol"] == "ICMPv4"
        assert profiles[0]["key"] == "icmp_any"
        assert profiles[0]["is_system_defined"] is True

    def test_custom_port_profile(self):
        rules = [
            {
                "original_id": "1",
                "is_system": False,
                "application": [{"protocol": "tcp", "port": "8080"}],
            },
        ]
        profiles, _ = _collect_firewall_app_port_profiles(rules)
        assert len(profiles) == 1
        assert profiles[0]["is_system_defined"] is False
        assert profiles[0]["custom_name"] == "ttc_fw_tcp_8080"

    def test_system_rules_skipped(self):
        rules = [
            {
                "original_id": "1",
                "is_system": True,
                "application": [{"protocol": "tcp", "port": "443"}],
            },
        ]
        profiles, rule_map = _collect_firewall_app_port_profiles(rules)
        assert len(profiles) == 0
        assert len(rule_map) == 0

    def test_dedup_across_rules(self):
        rules = [
            {"original_id": "1", "is_system": False,
             "application": [{"protocol": "tcp", "port": "443"}]},
            {"original_id": "2", "is_system": False,
             "application": [{"protocol": "tcp", "port": "443"}]},
        ]
        profiles, rule_map = _collect_firewall_app_port_profiles(rules)
        assert len(profiles) == 1
        assert "1" in profiles[0]["used_by_rule_ids"]
        assert "2" in profiles[0]["used_by_rule_ids"]

    def test_merge_profiles_dedup(self):
        nat_profiles = [
            {"key": "tcp_443", "protocol": "TCP", "ports": "443",
             "is_system_defined": True, "system_defined_name": "HTTPS",
             "custom_name": None, "used_by_rule_ids": ["nat_1"]},
        ]
        fw_profiles = [
            {"key": "tcp_443", "protocol": "TCP", "ports": "443",
             "is_system_defined": True, "system_defined_name": "HTTPS",
             "custom_name": None, "used_by_rule_ids": ["fw_1"],
             "source": "firewall"},
        ]
        merged = _merge_app_port_profiles(nat_profiles, fw_profiles)
        assert len(merged) == 1
        assert "nat_1" in merged[0]["used_by_rule_ids"]
        assert "fw_1" in merged[0]["used_by_rule_ids"]


class TestMigrationHCLGeneratorFirewallProfiles:
    def test_firewall_rule_has_app_port_profile_ids(self, full_hcl):
        """Rule 135393 has tcp/443 → should have app_port_profile_ids in firewall."""
        assert "app_port_profile_ids" in full_hcl

    def test_multi_service_rule_has_multiple_profile_ids(self, full_hcl):
        """Rule 135500 has tcp/80 + tcp/443 → two entries in app_port_profile_ids."""
        # Find the rule block for 135500 and check it has both profile references
        lines = full_hcl.split("\n")
        in_rule_block = False
        profile_ids_found = []
        for line in lines:
            if "migrated_135500" in line:
                in_rule_block = True
            if in_rule_block and "app_port_profile" in line and ".id" in line:
                profile_ids_found.append(line.strip())
            if in_rule_block and line.strip() == "}":
                break
        assert len(profile_ids_found) >= 2


# -----------------------------------------------------------------------
#  Rule names
# -----------------------------------------------------------------------


class TestMigrationHCLGeneratorRuleNames:
    def test_generic_name_uses_id_only(self, full_hcl):
        """Rule with name='New Rule' should use migrated_rule_{id} format."""
        assert "migrated_rule_135393" in full_hcl

    def test_meaningful_name_slugified(self, full_hcl):
        """Rule with meaningful name should include slugified name."""
        assert "migrated_135500_internal_to_any" in full_hcl

    def test_disabled_rule_name_slugified(self, full_hcl):
        """Rule 131075 name='disabled-rule' should be slugified."""
        assert "migrated_131075_disabled_rule" in full_hcl


# -----------------------------------------------------------------------
#  Integration
# -----------------------------------------------------------------------


class TestMigrationHCLGeneratorIntegration:
    def test_full_generation_all_sections(self, full_hcl):
        assert 'variable "vcd_url"' in full_hcl
        assert 'resource "vcd_nsxt_ip_set"' in full_hcl
        assert "vcd_nsxt_app_port_profile" in full_hcl
        assert 'resource "vcd_nsxt_firewall"' in full_hcl
        assert 'resource "vcd_nsxt_nat_rule"' in full_hcl
        assert 'resource "vcd_nsxt_edgegateway_static_route"' in full_hcl

    def test_rendering_order(self, full_hcl):
        """Templates should render in dependency order."""
        var_pos = full_hcl.index('variable "vcd_url"')
        ip_set_pos = full_hcl.index('resource "vcd_nsxt_ip_set"')
        app_port_pos = full_hcl.index("vcd_nsxt_app_port_profile")
        fw_pos = full_hcl.index('resource "vcd_nsxt_firewall"')
        nat_pos = full_hcl.index('resource "vcd_nsxt_nat_rule"')
        route_pos = full_hcl.index('resource "vcd_nsxt_edgegateway_static_route"')
        assert var_pos < ip_set_pos < app_port_pos < fw_pos < nat_pos < route_pos

    def test_no_legacy_resource_types(self, full_hcl):
        assert "vcd_edgegateway" not in full_hcl.replace("vcd_nsxt_edgegateway", "")
        assert "vcd_firewall_rules" not in full_hcl

    def test_edge_gateway_id_uses_variable(self, full_hcl):
        assert "var.target_edge_id" in full_hcl

    def test_org_uses_variable(self, full_hcl):
        assert "var.target_org" in full_hcl
