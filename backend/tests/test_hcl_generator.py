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
        })
        assert 'provider "vcd"' in hcl
        assert 'resource "vcd_org"' in hcl
        assert 'resource "vcd_org_vdc"' in hcl
        assert 'resource "vcd_nsxt_edgegateway"' in hcl

    def test_sections_rendered_in_order(self):
        """Base comes first, then org, then vdc, then edge."""
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
        })
        provider_pos = hcl.index('provider "vcd"')
        org_pos = hcl.index('resource "vcd_org"')
        vdc_pos = hcl.index('resource "vcd_org_vdc"')
        edge_pos = hcl.index('resource "vcd_nsxt_edgegateway"')
        assert provider_pos < org_pos < vdc_pos < edge_pos

    def test_backend_state_key_uses_org_slug(self):
        hcl = self.gen.generate({"org": {"name": "My Org (prod)"}})
        assert "my_org_prod/terraform.tfstate" in hcl
