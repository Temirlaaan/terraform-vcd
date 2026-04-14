"""Tests for app.core.hcl_generator — slug, hcl_escape, and HCL rendering."""

import pytest

from app.core.hcl_generator import HCLGenerator, _hcl_escape, _slug


# -----------------------------------------------------------------------
#  _slug
# -----------------------------------------------------------------------


class TestSlug:
    def test_simple_name(self):
        assert _slug("MyOrg") == "myorg"

    def test_spaces_become_underscores(self):
        assert _slug("My Org") == "my_org"

    def test_special_chars_stripped(self):
        assert _slug("My Org (prod)") == "my_org_prod"

    def test_leading_trailing_underscores_stripped(self):
        assert _slug("  --Hello--  ") == "hello"

    def test_consecutive_specials_collapse(self):
        assert _slug("a---b___c") == "a_b_c"

    def test_empty_string_returns_resource(self):
        assert _slug("") == "resource"

    def test_only_special_chars_returns_resource(self):
        assert _slug("!!!") == "resource"

    def test_digits_preserved(self):
        assert _slug("org-123") == "org_123"


# -----------------------------------------------------------------------
#  _hcl_escape
# -----------------------------------------------------------------------


class TestHclEscape:
    def test_plain_string_unchanged(self):
        assert _hcl_escape("hello world") == "hello world"

    def test_double_quotes_escaped(self):
        assert _hcl_escape('say "hi"') == 'say \\"hi\\"'

    def test_backslash_escaped(self):
        assert _hcl_escape("path\\to") == "path\\\\to"

    def test_newline_escaped(self):
        assert _hcl_escape("line1\nline2") == "line1\\nline2"

    def test_carriage_return_escaped(self):
        assert _hcl_escape("line1\rline2") == "line1\\rline2"

    def test_dollar_sign_escaped(self):
        assert _hcl_escape("${var.foo}") == "$${var.foo}"

    def test_combined_injection_attempt(self):
        """A crafted string that tries to break out of HCL quotes."""
        malicious = 'foo"\n}\nresource "null_resource" "evil" {'
        escaped = _hcl_escape(malicious)
        # Literal newlines must be escaped
        assert "\n" not in escaped
        # All double quotes must be escaped
        assert '"' not in escaped.replace('\\"', '')

    def test_non_string_coerced(self):
        assert _hcl_escape(42) == "42"


# -----------------------------------------------------------------------
#  HCLGenerator — base template
# -----------------------------------------------------------------------


class TestHCLGeneratorBase:
    """Tests for the base provider/backend block that is always rendered."""

    def setup_method(self):
        self.gen = HCLGenerator()

    def test_base_renders_with_defaults(self):
        hcl = self.gen.generate({"org": {"name": "test"}})
        assert 'provider "vcd"' in hcl
        assert "var.vcd_url" in hcl
        assert "var.vcd_password" in hcl
        assert 'bucket' in hcl

    def test_base_renders_without_org(self):
        """Base template must work even when org is not provided."""
        hcl = self.gen.generate({})
        assert 'provider "vcd"' in hcl
        assert "default/terraform.tfstate" in hcl

    def test_base_uses_custom_backend_bucket(self):
        hcl = self.gen.generate({"backend": {"bucket": "my-bucket"}})
        assert '"my-bucket"' in hcl

    def test_base_provider_org_override(self):
        hcl = self.gen.generate({"provider": {"org": "CustomOrg"}})
        assert '"CustomOrg"' in hcl

    def test_no_credentials_in_hcl(self):
        """Credentials must be via var references, never literal values."""
        hcl = self.gen.generate({
            "org": {"name": "Test Org", "is_enabled": True},
        })
        # Password should only appear in variable references and declarations
        for line in hcl.split("\n"):
            if "password" in line.lower() and "=" in line:
                # Assignment lines must reference var, not contain a literal
                assert "var." in line or "string" in line, (
                    f"Possible credential leak: {line}"
                )


# -----------------------------------------------------------------------
#  HCLGenerator — organization template
# -----------------------------------------------------------------------


class TestHCLGeneratorOrg:

    def setup_method(self):
        self.gen = HCLGenerator()

    def test_org_resource_rendered(self):
        hcl = self.gen.generate({"org": {"name": "Acme Corp", "is_enabled": True}})
        assert 'resource "vcd_org" "acme_corp"' in hcl
        assert 'name             = "Acme Corp"' in hcl

    def test_org_full_name_defaults_to_name(self):
        hcl = self.gen.generate({"org": {"name": "Acme"}})
        assert 'full_name        = "Acme"' in hcl

    def test_org_full_name_override(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme", "full_name": "Acme Corporation"}
        })
        assert 'full_name        = "Acme Corporation"' in hcl

    def test_org_description_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme", "description": "Test org"}
        })
        assert 'description      = "Test org"' in hcl

    def test_org_without_description_no_field(self):
        hcl = self.gen.generate({"org": {"name": "Acme"}})
        assert "description" not in hcl

    def test_org_metadata_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme", "metadata": {"env": "prod", "team": "infra"}}
        })
        assert 'env = "prod"' in hcl
        assert 'team = "infra"' in hcl

    def test_org_not_rendered_when_absent(self):
        hcl = self.gen.generate({})
        assert "vcd_org" not in hcl

    def test_org_hcl_escape_prevents_injection(self):
        """Description with quotes must be escaped, not break HCL structure."""
        hcl = self.gen.generate({
            "org": {"name": "Safe", "description": 'has "quotes" inside'}
        })
        assert 'has \\"quotes\\" inside' in hcl

    def test_org_metadata_keys_escaped(self):
        hcl = self.gen.generate({
            "org": {"name": "X", "metadata": {'key"evil': "val"}}
        })
        assert 'key\\"evil' in hcl


# -----------------------------------------------------------------------
#  HCLGenerator — VDC template
# -----------------------------------------------------------------------


class TestHCLGeneratorVdc:

    def setup_method(self):
        self.gen = HCLGenerator()

    def test_vdc_resource_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev VDC", "provider_vdc_name": "pvdc-01"},
        })
        assert 'resource "vcd_org_vdc" "dev_vdc"' in hcl
        assert 'provider_vdc_name = "pvdc-01"' in hcl

    def test_vdc_org_reference_defaults_to_org_name(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V1", "provider_vdc_name": "p1"},
        })
        assert 'org  = "Acme"' in hcl

    def test_vdc_compute_capacity(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {
                "name": "V1",
                "provider_vdc_name": "p1",
                "cpu_allocated": 2000,
                "cpu_limit": 4000,
                "memory_allocated": 8192,
                "memory_limit": 16384,
            },
        })
        assert "allocated = 2000" in hcl
        assert "limit     = 4000" in hcl
        assert "allocated = 8192" in hcl
        assert "limit     = 16384" in hcl

    def test_vdc_storage_profiles(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {
                "name": "V1",
                "provider_vdc_name": "p1",
                "storage_profiles": [
                    {"name": "Gold", "limit": 10240, "default": True},
                    {"name": "Silver", "limit": 5120, "default": False},
                ],
            },
        })
        assert 'name    = "Gold"' in hcl
        assert 'name    = "Silver"' in hcl
        assert "limit   = 10240" in hcl
        assert "default = true" in hcl

    def test_vdc_not_rendered_when_absent(self):
        hcl = self.gen.generate({"org": {"name": "Acme"}})
        assert "vcd_org_vdc" not in hcl

    def test_vdc_description_escaped(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {
                "name": "V1",
                "provider_vdc_name": "p1",
                "description": 'VDC for "testing"',
            },
        })
        assert 'VDC for \\"testing\\"' in hcl


# -----------------------------------------------------------------------
#  HCLGenerator — edge gateway template
# -----------------------------------------------------------------------


class TestHCLGeneratorEdge:

    def setup_method(self):
        self.gen = HCLGenerator()

    def _edge_config(self, **overrides):
        """Helper to build a minimal edge config dict."""
        base = {
            "name": "gw-01",
            "external_network_name": "ext-net",
            "subnet": {
                "gateway": "10.0.0.1",
                "prefix_length": 24,
                "primary_ip": "10.0.0.1",
            },
        }
        base.update(overrides)
        return base

    def test_edge_resource_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
            "edge": self._edge_config(),
        })
        assert 'resource "vcd_nsxt_edgegateway" "gw_01"' in hcl
        assert 'name' in hcl
        assert 'owner_id' in hcl
        assert 'external_network_id' in hcl

    def test_edge_data_sources_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
            "edge": self._edge_config(),
        })
        assert 'data "vcd_external_network_v2" "ext_net"' in hcl
        assert 'data "vcd_org_vdc" "dev_for_edge"' in hcl

    def test_edge_owner_id_references_vdc_data(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme Corp"},
            "vdc": {"name": "Prod VDC", "provider_vdc_name": "p1"},
            "edge": self._edge_config(),
        })
        assert "data.vcd_org_vdc.prod_vdc_for_edge.id" in hcl

    def test_edge_external_network_id_references_data(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(external_network_name="My ExtNet"),
        })
        assert "data.vcd_external_network_v2.my_extnet.id" in hcl

    def test_edge_subnet_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(),
        })
        assert "subnet {" in hcl
        assert 'gateway       = "10.0.0.1"' in hcl
        assert "prefix_length = 24" in hcl
        assert 'primary_ip    = "10.0.0.1"' in hcl

    def test_edge_allocated_ips_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(subnet={
                "gateway": "10.0.0.1",
                "prefix_length": 24,
                "primary_ip": "10.0.0.1",
                "start_address": "10.0.0.10",
                "end_address": "10.0.0.50",
            }),
        })
        assert "allocated_ips {" in hcl
        assert 'start_address = "10.0.0.10"' in hcl
        assert 'end_address   = "10.0.0.50"' in hcl

    def test_edge_no_allocated_ips_when_absent(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(),
        })
        assert "allocated_ips" not in hcl

    def test_edge_not_rendered_when_absent(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
        })
        assert "vcd_nsxt_edgegateway" not in hcl
        assert "vcd_external_network_v2" not in hcl

    def test_edge_description_escaped(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(description='Edge for "production"'),
        })
        assert 'Edge for \\"production\\"' in hcl

    def test_edge_dedicate_external_network(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(dedicate_external_network=True),
        })
        assert "dedicate_external_network = true" in hcl

    def test_edge_cluster_id_rendered(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(edge_cluster_id="urn:vcloud:edgeCluster:aaaa-1111"),
        })
        assert 'edge_cluster_id           = "urn:vcloud:edgeCluster:aaaa-1111"' in hcl

    def test_edge_cluster_id_escaped_prevents_injection(self):
        """Verify HCL injection via edge_cluster_id is neutralized."""
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(edge_cluster_id='urn:test"\n}\nresource "evil" {'),
        })
        assert '\n}\nresource "evil"' not in hcl
        assert '\\"' in hcl

    def test_edge_cluster_id_not_rendered_when_absent(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(),
        })
        assert "edge_cluster_id" not in hcl

    def test_no_legacy_fields_in_output(self):
        """Ensure no legacy vcd_edgegateway attributes appear."""
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": self._edge_config(),
        })
        assert "configuration" not in hcl
        assert "ha_enabled" not in hcl
        assert "distributed_routing" not in hcl
        assert "external_network {" not in hcl
        assert "netmask" not in hcl


# -----------------------------------------------------------------------
#  HCLGenerator — vcd_network_routed_v2 template
# -----------------------------------------------------------------------


class TestHCLGeneratorNetwork:

    def setup_method(self):
        self.gen = HCLGenerator()

    def _base_config(self, **network_overrides):
        """Helper to build a config with org, vdc, edge, and network."""
        network = {"name": "net-01", "gateway": "192.168.1.1", "prefix_length": 24}
        network.update(network_overrides)
        return {
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
            "edge": {
                "name": "gw-01",
                "external_network_name": "ext-net",
                "subnet": {
                    "gateway": "10.0.0.1",
                    "prefix_length": 24,
                    "primary_ip": "10.0.0.1",
                },
            },
            "network": network,
        }

    def test_network_resource_rendered(self):
        hcl = self.gen.generate(self._base_config())
        assert 'resource "vcd_network_routed_v2" "net_01"' in hcl

    def test_network_data_source_for_edge(self):
        hcl = self.gen.generate(self._base_config())
        assert 'data "vcd_nsxt_edgegateway" "gw_01_for_network"' in hcl

    def test_network_edge_gateway_id_references_data(self):
        hcl = self.gen.generate(self._base_config())
        assert "edge_gateway_id = data.vcd_nsxt_edgegateway.gw_01_for_network.id" in hcl

    def test_network_static_ip_pool_rendered(self):
        hcl = self.gen.generate(self._base_config(
            static_ip_pool={
                "start_address": "192.168.1.10",
                "end_address": "192.168.1.50",
            }
        ))
        assert "static_ip_pool {" in hcl
        assert 'start_address = "192.168.1.10"' in hcl
        assert 'end_address   = "192.168.1.50"' in hcl

    def test_network_no_static_pool_when_absent(self):
        hcl = self.gen.generate(self._base_config())
        assert "static_ip_pool" not in hcl

    def test_network_dns_rendered(self):
        hcl = self.gen.generate(self._base_config(dns1="8.8.8.8", dns2="8.8.4.4"))
        assert 'dns1            = "8.8.8.8"' in hcl
        assert 'dns2            = "8.8.4.4"' in hcl

    def test_network_no_dns_when_absent(self):
        hcl = self.gen.generate(self._base_config())
        assert "dns1" not in hcl
        assert "dns2" not in hcl

    def test_network_not_rendered_when_absent(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
            "edge": {
                "name": "gw-01",
                "external_network_name": "ext-net",
                "subnet": {
                    "gateway": "10.0.0.1",
                    "prefix_length": 24,
                    "primary_ip": "10.0.0.1",
                },
            },
        })
        assert "vcd_network_routed_v2" not in hcl
        assert "for_network" not in hcl

    def test_network_description_escaped(self):
        hcl = self.gen.generate(self._base_config(
            description='Net for "testing"'
        ))
        assert 'Net for \\"testing\\"' in hcl

    def test_network_gateway_and_prefix_rendered(self):
        hcl = self.gen.generate(self._base_config(gateway="10.10.0.1", prefix_length=28))
        assert 'gateway         = "10.10.0.1"' in hcl
        assert "prefix_length   = 28" in hcl

    def test_network_org_reference(self):
        hcl = self.gen.generate(self._base_config())
        # The network resource should reference the org
        lines = hcl.split("\n")
        in_network = False
        for line in lines:
            if 'resource "vcd_network_routed_v2"' in line:
                in_network = True
            if in_network and "org" in line and "=" in line:
                assert '"Acme"' in line
                break


# -----------------------------------------------------------------------
#  HCLGenerator — vcd_vapp template
# -----------------------------------------------------------------------


class TestHCLGeneratorVapp:

    def setup_method(self):
        self.gen = HCLGenerator()

    def _base_config(self, **vapp_overrides):
        """Helper to build a config with org, vdc, and vapp."""
        vapp = {"name": "web-app", "power_on": False}
        vapp.update(vapp_overrides)
        return {
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
            "vapp": vapp,
        }

    def test_vapp_resource_rendered(self):
        hcl = self.gen.generate(self._base_config())
        assert 'resource "vcd_vapp" "web_app"' in hcl

    def test_vapp_data_source_for_vdc(self):
        hcl = self.gen.generate(self._base_config())
        assert 'data "vcd_org_vdc" "dev_for_vapp"' in hcl

    def test_vapp_vdc_references_data(self):
        hcl = self.gen.generate(self._base_config())
        assert "vdc      = data.vcd_org_vdc.dev_for_vapp.name" in hcl

    def test_vapp_power_on_default_false(self):
        hcl = self.gen.generate(self._base_config())
        assert "power_on = false" in hcl

    def test_vapp_power_on_true(self):
        hcl = self.gen.generate(self._base_config(power_on=True))
        assert "power_on = true" in hcl

    def test_vapp_description_rendered(self):
        hcl = self.gen.generate(self._base_config(description="My vApp"))
        assert 'description = "My vApp"' in hcl

    def test_vapp_no_description_when_absent(self):
        hcl = self.gen.generate(self._base_config())
        assert "description" not in hcl

    def test_vapp_not_rendered_when_absent(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
        })
        assert "vcd_vapp" not in hcl
        assert "for_vapp" not in hcl

    def test_vapp_description_escaped(self):
        hcl = self.gen.generate(self._base_config(description='App for "testing"'))
        assert 'App for \\"testing\\"' in hcl


# -----------------------------------------------------------------------
#  HCLGenerator — vcd_vapp_vm template
# -----------------------------------------------------------------------


class TestHCLGeneratorVm:

    def setup_method(self):
        self.gen = HCLGenerator()

    def _base_config(self, **vm_overrides):
        """Helper to build a config with org, vdc, vapp, and vm."""
        vm = {
            "name": "web-01",
            "computer_name": "web01",
            "catalog_name": "my-catalog",
            "template_name": "ubuntu-22",
            "memory": 1024,
            "cpus": 1,
            "cpu_cores": 1,
            "power_on": True,
        }
        vm.update(vm_overrides)
        return {
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
            "vapp": {"name": "web-app"},
            "vm": vm,
        }

    def test_vm_resource_rendered(self):
        hcl = self.gen.generate(self._base_config())
        assert 'resource "vcd_vapp_vm" "web_01"' in hcl

    def test_catalog_data_source(self):
        hcl = self.gen.generate(self._base_config())
        assert 'data "vcd_catalog" "my_catalog"' in hcl

    def test_template_data_source(self):
        hcl = self.gen.generate(self._base_config())
        assert 'data "vcd_catalog_vapp_template" "ubuntu_22"' in hcl

    def test_template_refs_catalog(self):
        hcl = self.gen.generate(self._base_config())
        assert "data.vcd_catalog.my_catalog.id" in hcl

    def test_vapp_template_id_refs_data(self):
        hcl = self.gen.generate(self._base_config())
        assert "data.vcd_catalog_vapp_template.ubuntu_22.id" in hcl

    def test_compute_values(self):
        hcl = self.gen.generate(self._base_config(memory=2048, cpus=4, cpu_cores=2))
        assert "memory           = 2048" in hcl
        assert "cpus             = 4" in hcl
        assert "cpu_cores        = 2" in hcl

    def test_power_on_true_default(self):
        hcl = self.gen.generate(self._base_config())
        assert "power_on         = true" in hcl

    def test_power_on_false(self):
        hcl = self.gen.generate(self._base_config(power_on=False))
        assert "power_on         = false" in hcl

    def test_network_block_rendered(self):
        hcl = self.gen.generate(self._base_config(
            network={"type": "org", "name": "net-01", "ip_allocation_mode": "POOL"}
        ))
        assert "network {" in hcl
        assert 'type               = "org"' in hcl
        assert 'name               = "net-01"' in hcl
        assert 'ip_allocation_mode = "POOL"' in hcl

    def test_network_manual_ip(self):
        hcl = self.gen.generate(self._base_config(
            network={"type": "org", "name": "net-01", "ip_allocation_mode": "MANUAL", "ip": "10.0.0.5"}
        ))
        assert 'ip                 = "10.0.0.5"' in hcl

    def test_no_network_when_absent(self):
        hcl = self.gen.generate(self._base_config())
        assert "network {" not in hcl

    def test_storage_profile(self):
        hcl = self.gen.generate(self._base_config(storage_profile="Gold"))
        assert 'storage_profile  = "Gold"' in hcl

    def test_no_storage_profile(self):
        hcl = self.gen.generate(self._base_config())
        assert "storage_profile" not in hcl

    def test_description(self):
        hcl = self.gen.generate(self._base_config(description="My VM"))
        assert 'description      = "My VM"' in hcl

    def test_description_escaped(self):
        hcl = self.gen.generate(self._base_config(description='VM for "testing"'))
        assert 'VM for \\"testing\\"' in hcl

    def test_not_rendered_when_absent(self):
        hcl = self.gen.generate({
            "org": {"name": "Acme"},
            "vdc": {"name": "Dev", "provider_vdc_name": "p1"},
            "vapp": {"name": "web-app"},
        })
        assert "vcd_vapp_vm" not in hcl
        assert "vcd_catalog" not in hcl

    def test_vm_references_vapp_name(self):
        hcl = self.gen.generate(self._base_config())
        assert 'vapp_name        = "web-app"' in hcl

    def test_vm_references_org_and_vdc(self):
        hcl = self.gen.generate(self._base_config())
        # Within the vcd_vapp_vm resource block
        lines = hcl.split("\n")
        in_vm = False
        found_org = False
        found_vdc = False
        for line in lines:
            if 'resource "vcd_vapp_vm"' in line:
                in_vm = True
            if in_vm and line.strip().startswith("org") and "=" in line:
                assert '"Acme"' in line
                found_org = True
            if in_vm and line.strip().startswith("vdc") and "=" in line:
                assert '"Dev"' in line
                found_vdc = True
            if in_vm and line.strip() == "}":
                break
        assert found_org
        assert found_vdc


# -----------------------------------------------------------------------
#  HCLGenerator — combined output
# -----------------------------------------------------------------------


class TestHCLGeneratorCombined:

    def setup_method(self):
        self.gen = HCLGenerator()

    def test_full_config_renders_all_sections(self):
        hcl = self.gen.generate({
            "provider": {"org": "System"},
            "backend": {"bucket": "state"},
            "org": {"name": "Acme", "is_enabled": True},
            "vdc": {"name": "Dev", "provider_vdc_name": "pvdc-01"},
            "edge": {
                "name": "gw-01",
                "external_network_name": "ext-net",
                "subnet": {
                    "gateway": "10.0.0.1",
                    "prefix_length": 24,
                    "primary_ip": "10.0.0.1",
                },
            },
            "network": {
                "name": "net-01",
                "gateway": "192.168.1.1",
                "prefix_length": 24,
            },
            "vapp": {"name": "web-app"},
            "vm": {
                "name": "web-01",
                "computer_name": "web01",
                "catalog_name": "my-catalog",
                "template_name": "ubuntu-22",
            },
        })
        assert 'provider "vcd"' in hcl
        assert 'resource "vcd_org"' in hcl
        assert 'resource "vcd_org_vdc"' in hcl
        assert 'resource "vcd_nsxt_edgegateway"' in hcl
        assert 'resource "vcd_network_routed_v2"' in hcl
        assert 'resource "vcd_vapp"' in hcl
        assert 'resource "vcd_vapp_vm"' in hcl

    def test_sections_rendered_in_order(self):
        """Base comes first, then org, vdc, edge, network, vapp, vm."""
        hcl = self.gen.generate({
            "org": {"name": "A"},
            "vdc": {"name": "V", "provider_vdc_name": "p"},
            "edge": {
                "name": "E",
                "external_network_name": "ext",
                "subnet": {
                    "gateway": "10.0.0.1",
                    "prefix_length": 24,
                    "primary_ip": "10.0.0.1",
                },
            },
            "network": {
                "name": "N",
                "gateway": "192.168.1.1",
                "prefix_length": 24,
            },
            "vapp": {"name": "APP"},
            "vm": {
                "name": "VM1",
                "computer_name": "vm1",
                "catalog_name": "cat",
                "template_name": "tpl",
            },
        })
        provider_pos = hcl.index('provider "vcd"')
        org_pos = hcl.index('resource "vcd_org"')
        vdc_pos = hcl.index('resource "vcd_org_vdc"')
        edge_pos = hcl.index('resource "vcd_nsxt_edgegateway"')
        network_pos = hcl.index('resource "vcd_network_routed_v2"')
        vapp_pos = hcl.index('resource "vcd_vapp"')
        vm_pos = hcl.index('resource "vcd_vapp_vm"')
        assert provider_pos < org_pos < vdc_pos < edge_pos < network_pos < vapp_pos < vm_pos

    def test_backend_state_key_uses_org_slug(self):
        hcl = self.gen.generate({"org": {"name": "My Org (prod)"}})
        assert "my_org_prod/terraform.tfstate" in hcl
