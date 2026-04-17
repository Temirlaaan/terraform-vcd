"""Tests for app.migration.normalizer — XML → canonical JSON normalization."""

import xml.etree.ElementTree as StdET

import pytest

from app.migration.normalizer import (
    SYSTEM_PROFILES,
    normalize_edge_snapshot,
    _build_app_port_profile_key,
    _classify_rule_type,
    _normalize_action,
    _normalize_edge_metadata,
    _normalize_firewall,
    _normalize_nat,
    _normalize_routing,
    _resolve_system_profile,
)


# -----------------------------------------------------------------------
#  XML Fixtures
# -----------------------------------------------------------------------

FIREWALL_XML = """\
<firewall>
  <enabled>true</enabled>
  <defaultPolicy>
    <action>accept</action>
    <loggingEnabled>false</loggingEnabled>
  </defaultPolicy>
  <firewallRules>
    <firewallRule>
      <id>135393</id>
      <name>New Rule</name>
      <ruleType>user</ruleType>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <action>accept</action>
      <source>
        <exclude>false</exclude>
        <ipAddress>10.121.24.3/32</ipAddress>
        <ipAddress>10.121.44.0/24</ipAddress>
        <ipAddress>10.121.43.0/24</ipAddress>
      </source>
      <destination>
        <exclude>false</exclude>
        <ipAddress>192.168.1.0/24</ipAddress>
      </destination>
      <application>
        <service>
          <protocol>tcp</protocol>
          <port>443</port>
        </service>
      </application>
    </firewallRule>
    <firewallRule>
      <id>131073</id>
      <name>firewall</name>
      <ruleType>internal_high</ruleType>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <action>accept</action>
    </firewallRule>
    <firewallRule>
      <id>131074</id>
      <name>vse-self-rule</name>
      <ruleType>user</ruleType>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <action>accept</action>
      <source>
        <exclude>false</exclude>
        <vnicGroupId>vse-abcdef123456</vnicGroupId>
      </source>
    </firewallRule>
    <firewallRule>
      <id>131075</id>
      <name>disabled-rule</name>
      <ruleType>user</ruleType>
      <enabled>false</enabled>
      <loggingEnabled>true</loggingEnabled>
      <action>deny</action>
      <source>
        <exclude>true</exclude>
        <ipAddress>10.0.0.1</ipAddress>
      </source>
    </firewallRule>
    <firewallRule>
      <id>131076</id>
      <name>default rule</name>
      <ruleType>default_policy</ruleType>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <action>deny</action>
    </firewallRule>
    <firewallRule>
      <id>135500</id>
      <name>internal-to-any</name>
      <ruleType>user</ruleType>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <action>accept</action>
      <source>
        <exclude>false</exclude>
        <vnicGroupId>internal</vnicGroupId>
      </source>
      <application>
        <service>
          <protocol>tcp</protocol>
          <port>80</port>
        </service>
        <service>
          <protocol>tcp</protocol>
          <port>443</port>
        </service>
      </application>
    </firewallRule>
  </firewallRules>
</firewall>
"""

NAT_XML = """\
<nat>
  <enabled>true</enabled>
  <natRules>
    <natRule>
      <ruleId>200825</ruleId>
      <description>Access to SSH</description>
      <ruleType>user</ruleType>
      <action>dnat</action>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <originalAddress>37.208.43.38</originalAddress>
      <translatedAddress>10.10.0.19</translatedAddress>
      <originalPort>443</originalPort>
      <translatedPort>443</translatedPort>
      <protocol>tcp</protocol>
    </natRule>
    <natRule>
      <ruleId>200826</ruleId>
      <description>Outbound SNAT</description>
      <ruleType>user</ruleType>
      <action>snat</action>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <originalAddress>10.10.0.0/24</originalAddress>
      <translatedAddress>37.208.43.38</translatedAddress>
      <protocol>any</protocol>
    </natRule>
    <natRule>
      <ruleId>233621</ruleId>
      <description>3cx-rtp</description>
      <ruleType>user</ruleType>
      <action>dnat</action>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <originalAddress>37.208.43.84</originalAddress>
      <translatedAddress>10.121.10.18</translatedAddress>
      <originalPort>9000-10999</originalPort>
      <translatedPort>9000-10999</translatedPort>
      <protocol>udp</protocol>
    </natRule>
    <natRule>
      <ruleId>200827</ruleId>
      <description>Duplicate HTTPS</description>
      <ruleType>user</ruleType>
      <action>dnat</action>
      <enabled>true</enabled>
      <loggingEnabled>false</loggingEnabled>
      <originalAddress>37.208.43.39</originalAddress>
      <translatedAddress>10.10.0.20</translatedAddress>
      <originalPort>443</originalPort>
      <translatedPort>443</translatedPort>
      <protocol>tcp</protocol>
    </natRule>
  </natRules>
</nat>
"""

ROUTING_XML = """\
<routing>
  <staticRouting>
    <staticRoutes>
      <route>
        <name>to-internal</name>
        <network>10.121.42.0/24</network>
        <nextHop>172.24.0.253</nextHop>
        <mtu>1500</mtu>
        <adminDistance>1</adminDistance>
        <vnic>2</vnic>
        <description>Internal network route</description>
      </route>
      <route>
        <name>to-backup</name>
        <network>10.121.43.0/24</network>
        <nextHop>172.24.0.254</nextHop>
        <mtu>1500</mtu>
        <vnic>2</vnic>
      </route>
      <route>
        <name>default</name>
        <network>0.0.0.0/0</network>
        <nextHop>172.24.0.1</nextHop>
        <mtu>1500</mtu>
        <adminDistance>1</adminDistance>
        <vnic>0</vnic>
      </route>
    </staticRoutes>
  </staticRouting>
</routing>
"""

EDGE_METADATA_XML = """\
<EdgeGateway xmlns="http://www.vmware.com/vcloud/v1.5" name="TTC_Telco_EDGE"
             id="urn:vcloud:gateway:b6b3181a-2596-44c5-9991-c4c54c050bcb"
             status="1" href="https://vcd01.t-cloud.kz/api/admin/edgeGateway/b6b3181a-2596-44c5-9991-c4c54c050bcb">
  <Configuration>
    <GatewayBackingConfig>compact</GatewayBackingConfig>
    <GatewayInterfaces>
      <GatewayInterface>
        <Name>Internet</Name>
        <InterfaceType>uplink</InterfaceType>
        <SubnetParticipation>
          <Gateway>37.208.43.1</Gateway>
          <Netmask>255.255.255.0</Netmask>
          <IpAddress>37.208.43.38</IpAddress>
        </SubnetParticipation>
      </GatewayInterface>
      <GatewayInterface>
        <Name>Internal-Net</Name>
        <InterfaceType>internal</InterfaceType>
        <SubnetParticipation>
          <Gateway>10.10.0.1</Gateway>
          <Netmask>255.255.255.0</Netmask>
          <IpAddress>10.10.0.1</IpAddress>
        </SubnetParticipation>
      </GatewayInterface>
    </GatewayInterfaces>
    <GatewayBackingType>NSXV_BACKED</GatewayBackingType>
  </Configuration>
</EdgeGateway>
"""


# -----------------------------------------------------------------------
#  _normalize_action
# -----------------------------------------------------------------------


class TestNormalizeAction:
    def test_accept_becomes_allow(self):
        assert _normalize_action("accept") == "ALLOW"

    def test_deny_becomes_drop(self):
        assert _normalize_action("deny") == "DROP"

    def test_case_insensitive(self):
        assert _normalize_action("Accept") == "ALLOW"
        assert _normalize_action("DENY") == "DROP"


# -----------------------------------------------------------------------
#  _classify_rule_type
# -----------------------------------------------------------------------


class TestClassifyRuleType:
    def test_user_is_not_system(self):
        assert _classify_rule_type("user") is False

    def test_internal_high_is_not_system(self):
        """internal_high is a priority level, not a system marker."""
        assert _classify_rule_type("internal_high") is False

    def test_default_policy_is_system(self):
        assert _classify_rule_type("default_policy") is True


# -----------------------------------------------------------------------
#  _build_app_port_profile_key
# -----------------------------------------------------------------------


class TestBuildAppPortProfileKey:
    def test_tcp_443(self):
        assert _build_app_port_profile_key("tcp", "443") == "tcp_443"

    def test_udp_port_range(self):
        assert _build_app_port_profile_key("udp", "9000-10999") == "udp_9000-10999"

    def test_icmp_any(self):
        assert _build_app_port_profile_key("icmp", "any") == "icmp_any"


# -----------------------------------------------------------------------
#  _resolve_system_profile
# -----------------------------------------------------------------------


class TestResolveSystemProfile:
    def test_known_profile_https(self):
        assert _resolve_system_profile("tcp_443") == "HTTPS"

    def test_known_profile_ssh(self):
        assert _resolve_system_profile("tcp_22") == "SSH"

    def test_unknown_returns_none(self):
        assert _resolve_system_profile("tcp_8080") is None


# -----------------------------------------------------------------------
#  _normalize_firewall
# -----------------------------------------------------------------------


class TestNormalizeFirewall:
    def setup_method(self):
        self.result = _normalize_firewall(FIREWALL_XML)

    def test_user_rule_parsed(self):
        rules = self.result["rules"]
        user_rules = [r for r in rules if r["original_id"] == "135393"]
        assert len(user_rules) == 1
        rule = user_rules[0]
        assert rule["name"] == "New Rule"
        assert rule["rule_type"] == "user"
        assert rule["enabled"] is True

    def test_source_ips_collected(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "135393")
        assert rule["source"]["ip_addresses"] == [
            "10.121.24.3/32",
            "10.121.44.0/24",
            "10.121.43.0/24",
        ]

    def test_internal_high_is_not_system(self):
        """internal_high is a priority level, not a system rule type."""
        rule = next(r for r in self.result["rules"] if r["original_id"] == "131073")
        assert rule["is_system"] is False

    def test_vse_rule_skipped(self):
        """Rules with vnicGroupId containing 'vse' should be excluded."""
        ids = [r["original_id"] for r in self.result["rules"]]
        assert "131074" not in ids

    def test_action_normalized(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "135393")
        assert rule["action"] == "ALLOW"

    def test_application_ports_parsed(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "135393")
        assert rule["application"] == [{"protocol": "tcp", "port": "443"}]

    def test_disabled_rule_preserved(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "131075")
        assert rule["enabled"] is False
        assert rule["logging"] is True
        assert rule["action"] == "DROP"
        assert rule["source"]["exclude"] is True

    def test_default_action_captured(self):
        assert self.result["default_action_source"] == "ALLOW"

    def test_enabled_flag(self):
        assert self.result["enabled"] is True

    def test_default_policy_rule_flagged(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "131076")
        assert rule["is_system"] is True

    def test_destination_ips_collected(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "135393")
        assert rule["destination"]["ip_addresses"] == ["192.168.1.0/24"]

    def test_vnic_group_id_internal_parsed(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "135500")
        assert rule["source"]["vnic_group_ids"] == ["internal"]

    def test_multi_service_application_parsed(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "135500")
        assert len(rule["application"]) == 2
        assert rule["application"][0] == {"protocol": "tcp", "port": "80"}
        assert rule["application"][1] == {"protocol": "tcp", "port": "443"}


# -----------------------------------------------------------------------
#  _normalize_nat
# -----------------------------------------------------------------------


class TestNormalizeNat:
    def setup_method(self):
        self.result = _normalize_nat(NAT_XML)

    def test_dnat_rule_parsed(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "200825")
        assert rule["action"] == "DNAT"
        assert rule["description"] == "Access to SSH"
        assert rule["original_address"] == "37.208.43.38"
        assert rule["translated_address"] == "10.10.0.19"
        assert rule["original_port"] == "443"
        assert rule["translated_port"] == "443"

    def test_snat_rule_parsed(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "200826")
        assert rule["action"] == "SNAT"
        assert rule["original_address"] == "10.10.0.0/24"
        assert rule["translated_address"] == "37.208.43.38"

    def test_port_range_parsed(self):
        rule = next(r for r in self.result["rules"] if r["original_id"] == "233621")
        assert rule["original_port"] == "9000-10999"
        assert rule["translated_port"] == "9000-10999"
        assert rule["protocol"] == "udp"

    def test_app_port_profiles_deduped(self):
        """tcp_443 appears in rules 200825 and 200827, but profile should be deduped."""
        profiles = self.result["required_app_port_profiles"]
        tcp_443_profiles = [p for p in profiles if p["key"] == "tcp_443"]
        assert len(tcp_443_profiles) == 1
        profile = tcp_443_profiles[0]
        assert "200825" in profile["used_by_rule_ids"]
        assert "200827" in profile["used_by_rule_ids"]

    def test_system_profile_detected(self):
        profile = next(
            p for p in self.result["required_app_port_profiles"] if p["key"] == "tcp_443"
        )
        assert profile["is_system_defined"] is True
        assert profile["system_defined_name"] == "HTTPS"
        assert profile["custom_name"] is None

    def test_custom_profile_generated(self):
        profile = next(
            p
            for p in self.result["required_app_port_profiles"]
            if p["key"] == "udp_9000-10999"
        )
        assert profile["is_system_defined"] is False
        assert profile["system_defined_name"] is None
        assert profile["custom_name"] is not None
        assert "udp" in profile["custom_name"].lower()

    def test_protocol_normalized_to_upper(self):
        profile = next(
            p for p in self.result["required_app_port_profiles"] if p["key"] == "tcp_443"
        )
        assert profile["protocol"] == "TCP"

    def test_snat_no_app_port_profile(self):
        """SNAT rules with protocol=any should not generate app port profiles."""
        rule = next(r for r in self.result["rules"] if r["original_id"] == "200826")
        assert rule["needs_app_port_profile"] is False

    def test_enabled_flag(self):
        assert self.result["enabled"] is True


# -----------------------------------------------------------------------
#  _normalize_routing
# -----------------------------------------------------------------------


class TestNormalizeRouting:
    def setup_method(self):
        self.result = _normalize_routing(ROUTING_XML)

    def test_static_route_parsed(self):
        route = next(
            r for r in self.result["static_routes"] if r["network"] == "10.121.42.0/24"
        )
        assert route["next_hop"] == "172.24.0.253"
        assert route["mtu"] == 1500
        assert route["description"] == "Internal network route"

    def test_default_route_skipped(self):
        networks = [r["network"] for r in self.result["static_routes"]]
        assert "0.0.0.0/0" not in networks

    def test_vnic_field_stripped(self):
        for route in self.result["static_routes"]:
            assert "vnic" not in route

    def test_multiple_routes(self):
        assert len(self.result["static_routes"]) == 2

    def test_admin_distance_default(self):
        route = next(
            r for r in self.result["static_routes"] if r["network"] == "10.121.43.0/24"
        )
        assert route["admin_distance"] == 1


# -----------------------------------------------------------------------
#  _normalize_edge_metadata
# -----------------------------------------------------------------------


class TestNormalizeEdgeMetadata:
    def setup_method(self):
        self.result = _normalize_edge_metadata(EDGE_METADATA_XML)

    def test_edge_name_extracted(self):
        assert self.result["name"] == "TTC_Telco_EDGE"

    def test_interfaces_parsed(self):
        assert len(self.result["interfaces"]) == 2
        uplink = next(i for i in self.result["interfaces"] if i["type"] == "uplink")
        assert uplink["name"] == "Internet"
        internal = next(i for i in self.result["interfaces"] if i["type"] == "internal")
        assert internal["name"] == "Internal-Net"

    def test_backing_type_extracted(self):
        assert self.result["backing_type"] == "NSXV_BACKED"

    def test_interface_subnets(self):
        uplink = next(i for i in self.result["interfaces"] if i["type"] == "uplink")
        assert len(uplink["subnets"]) >= 1
        subnet = uplink["subnets"][0]
        assert subnet["gateway"] == "37.208.43.1"
        assert subnet["netmask"] == "255.255.255.0"
        assert subnet["ip_address"] == "37.208.43.38"


# -----------------------------------------------------------------------
#  normalize_edge_snapshot (integration)
# -----------------------------------------------------------------------


class TestNormalizeEdgeSnapshot:
    def setup_method(self):
        self.raw_xmls = {
            "edge_metadata.xml": EDGE_METADATA_XML,
            "firewall_config.xml": FIREWALL_XML,
            "nat_config.xml": NAT_XML,
            "routing_config.xml": ROUTING_XML,
        }
        self.result = normalize_edge_snapshot(self.raw_xmls)

    def test_full_snapshot_integration(self):
        assert "source" in self.result
        assert "edge" in self.result
        assert "firewall" in self.result
        assert "nat" in self.result
        assert "routing" in self.result

        # Firewall: 5 rules total (vse rule skipped from 6)
        assert len(self.result["firewall"]["rules"]) == 5

        # NAT: 4 rules
        assert len(self.result["nat"]["rules"]) == 4

        # Routing: 2 routes (default skipped)
        assert len(self.result["routing"]["static_routes"]) == 2

        # Edge metadata
        assert self.result["edge"]["name"] == "TTC_Telco_EDGE"

    def test_schema_version_is_1(self):
        assert self.result["schema_version"] == 1

    def test_source_metadata_populated(self):
        source = self.result["source"]
        assert source["edge_name"] == "TTC_Telco_EDGE"
        assert source["backing_type"] == "NSXV_BACKED"
        assert "snapshot_at" in source

    def test_snapshot_missing_key_raises(self):
        with pytest.raises(ValueError, match="Missing required XML keys"):
            normalize_edge_snapshot({"edge_metadata.xml": EDGE_METADATA_XML})


# -----------------------------------------------------------------------
#  Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_firewall_empty_rules_container(self):
        xml = "<firewall><enabled>true</enabled></firewall>"
        result = _normalize_firewall(xml)
        assert result["rules"] == []
        assert result["enabled"] is True

    def test_nat_empty_rules_container(self):
        xml = "<nat><enabled>false</enabled></nat>"
        result = _normalize_nat(xml)
        assert result["rules"] == []
        assert result["required_app_port_profiles"] == []
        assert result["enabled"] is False

    def test_routing_empty_static_routes(self):
        xml = "<routing><staticRouting></staticRouting></routing>"
        result = _normalize_routing(xml)
        assert result["static_routes"] == []

    def test_routing_invalid_mtu_uses_default(self):
        xml = """
        <routing>
          <staticRouting>
            <staticRoutes>
              <route>
                <network>10.0.0.0/24</network>
                <nextHop>10.0.0.1</nextHop>
                <mtu>invalid</mtu>
              </route>
            </staticRoutes>
          </staticRouting>
        </routing>
        """
        result = _normalize_routing(xml)
        assert result["static_routes"][0]["mtu"] == 1500

    def test_routing_invalid_admin_distance_uses_default(self):
        xml = """
        <routing>
          <staticRouting>
            <staticRoutes>
              <route>
                <network>10.0.0.0/24</network>
                <nextHop>10.0.0.1</nextHop>
                <adminDistance>bad</adminDistance>
              </route>
            </staticRoutes>
          </staticRouting>
        </routing>
        """
        result = _normalize_routing(xml)
        assert result["static_routes"][0]["admin_distance"] == 1

    def test_invalid_xml_raises_parse_error(self):
        with pytest.raises(StdET.ParseError):
            _normalize_firewall("not xml at all")

    def test_internal_high_with_vse_filtered_but_internal_kept(self):
        """internal_high + vse → filtered; internal_high + internal → kept."""
        xml = """
        <firewall>
          <enabled>true</enabled>
          <defaultPolicy><action>deny</action></defaultPolicy>
          <firewallRules>
            <firewallRule>
              <id>1001</id><name>vse-system</name>
              <ruleType>internal_high</ruleType>
              <enabled>true</enabled><loggingEnabled>false</loggingEnabled>
              <action>accept</action>
              <source>
                <vnicGroupId>vse-abc123</vnicGroupId>
              </source>
            </firewallRule>
            <firewallRule>
              <id>1002</id><name>dns</name>
              <ruleType>internal_high</ruleType>
              <enabled>true</enabled><loggingEnabled>false</loggingEnabled>
              <action>accept</action>
              <source>
                <vnicGroupId>internal</vnicGroupId>
              </source>
              <application>
                <service>
                  <protocol>udp</protocol>
                  <port>53</port>
                </service>
                <service>
                  <protocol>tcp</protocol>
                  <port>53</port>
                </service>
              </application>
            </firewallRule>
          </firewallRules>
        </firewall>
        """
        result = _normalize_firewall(xml)
        ids = [r["original_id"] for r in result["rules"]]
        # vse rule filtered by _has_vse_vnic
        assert "1001" not in ids
        # internal rule kept — internal_high is not a system rule type
        assert "1002" in ids
        dns_rule = next(r for r in result["rules"] if r["original_id"] == "1002")
        assert dns_rule["is_system"] is False
        assert dns_rule["source"]["vnic_group_ids"] == ["internal"]
        assert len(dns_rule["application"]) == 2

    def test_firewall_rule_no_application(self):
        xml = """
        <firewall>
          <enabled>true</enabled>
          <defaultPolicy><action>deny</action></defaultPolicy>
          <firewallRules>
            <firewallRule>
              <id>999</id><name>no-app</name><ruleType>user</ruleType>
              <enabled>true</enabled><loggingEnabled>false</loggingEnabled>
              <action>accept</action>
            </firewallRule>
          </firewallRules>
        </firewall>
        """
        result = _normalize_firewall(xml)
        assert result["rules"][0]["application"] == []
