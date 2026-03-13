"""Tests for app.schemas.terraform — Pydantic validation and safe name checks."""

import pytest
from pydantic import ValidationError

from app.schemas.terraform import (
    EdgeGatewayConfig,
    EdgeSubnetConfig,
    OrgConfig,
    TerraformConfig,
    TerraformDestroyRequest,
    VdcConfig,
    _validate_safe_name,
)


# -----------------------------------------------------------------------
#  _validate_safe_name
# -----------------------------------------------------------------------


class TestValidateSafeName:
    def test_valid_simple_name(self):
        assert _validate_safe_name("Acme Corp", "test") == "Acme Corp"

    def test_valid_with_digits(self):
        assert _validate_safe_name("org-123", "test") == "org-123"

    def test_valid_with_parens(self):
        assert _validate_safe_name("Org (prod)", "test") == "Org (prod)"

    def test_valid_with_underscores(self):
        assert _validate_safe_name("my_org", "test") == "my_org"

    def test_strips_whitespace(self):
        assert _validate_safe_name("  Acme  ", "test") == "Acme"

    def test_empty_after_strip_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_safe_name("   ", "test")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_safe_name("", "test")

    def test_slashes_rejected(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("../../etc/passwd", "test")

    def test_dots_rejected(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("org.name", "test")

    def test_semicolon_rejected(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("org;drop table", "test")

    def test_backticks_rejected(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("`rm -rf /`", "test")

    def test_dollar_rejected(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("$HOME", "test")

    def test_newline_rejected(self):
        """Newlines must be blocked — they could break path construction."""
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("org\nname", "test")

    def test_tab_rejected(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("org\tname", "test")

    def test_max_length_255_accepted(self):
        name = "a" * 255
        assert _validate_safe_name(name, "test") == name

    def test_over_255_rejected(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_safe_name("a" * 256, "test")


# -----------------------------------------------------------------------
#  OrgConfig
# -----------------------------------------------------------------------


class TestOrgConfig:
    def test_valid_org(self):
        org = OrgConfig(name="Acme Corp")
        assert org.name == "Acme Corp"
        assert org.is_enabled is True

    def test_org_name_stripped(self):
        org = OrgConfig(name="  Acme  ")
        assert org.name == "Acme"

    def test_org_name_with_slashes_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            OrgConfig(name="../../evil")
        assert "invalid characters" in str(exc_info.value)

    def test_org_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            OrgConfig(name="")

    def test_org_defaults(self):
        org = OrgConfig(name="Test")
        assert org.delete_force is False
        assert org.delete_recursive is False
        assert org.metadata is None
        assert org.description is None

    def test_org_with_all_fields(self):
        org = OrgConfig(
            name="Full Org",
            full_name="Full Organization",
            description="A test org",
            is_enabled=False,
            delete_force=True,
            delete_recursive=True,
            metadata={"env": "prod"},
        )
        assert org.full_name == "Full Organization"
        assert org.metadata == {"env": "prod"}


# -----------------------------------------------------------------------
#  VdcConfig
# -----------------------------------------------------------------------


class TestVdcConfig:
    def test_valid_vdc(self):
        vdc = VdcConfig(name="Dev VDC", provider_vdc_name="pvdc-01")
        assert vdc.name == "Dev VDC"
        assert vdc.allocation_model == "AllocationVApp"

    def test_vdc_name_with_dots_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            VdcConfig(name="vdc.evil", provider_vdc_name="p")
        assert "invalid characters" in str(exc_info.value)

    def test_vdc_missing_provider_vdc_rejected(self):
        with pytest.raises(ValidationError):
            VdcConfig(name="Good VDC")

    def test_vdc_negative_cpu_rejected(self):
        with pytest.raises(ValidationError):
            VdcConfig(name="V", provider_vdc_name="p", cpu_allocated=-1)

    def test_vdc_storage_profiles(self):
        vdc = VdcConfig(
            name="V",
            provider_vdc_name="p",
            storage_profiles=[
                {"name": "Gold", "limit": 10240, "default": True},
            ],
        )
        assert len(vdc.storage_profiles) == 1
        assert vdc.storage_profiles[0].name == "Gold"

    def test_vdc_defaults(self):
        vdc = VdcConfig(name="V", provider_vdc_name="p")
        assert vdc.cpu_allocated == 0
        assert vdc.memory_limit == 0
        assert vdc.enabled is True
        assert vdc.enable_thin_provisioning is True
        assert vdc.enable_fast_provisioning is False


# -----------------------------------------------------------------------
#  TerraformConfig
# -----------------------------------------------------------------------


class TestTerraformConfig:
    def test_default_config(self):
        config = TerraformConfig()
        assert config.provider.org == "System"
        assert config.backend.bucket == "terraform-state"
        assert config.org is None
        assert config.vdc is None

    def test_to_template_dict_minimal(self):
        config = TerraformConfig()
        d = config.to_template_dict()
        assert "provider" in d
        assert "backend" in d
        assert "org" not in d
        assert "vdc" not in d

    def test_to_template_dict_with_org(self):
        config = TerraformConfig(org=OrgConfig(name="Acme"))
        d = config.to_template_dict()
        assert d["org"]["name"] == "Acme"
        # None fields should be excluded
        assert "description" not in d["org"]

    def test_to_template_dict_with_vdc(self):
        config = TerraformConfig(
            org=OrgConfig(name="Acme"),
            vdc=VdcConfig(name="Dev", provider_vdc_name="pvdc-01"),
        )
        d = config.to_template_dict()
        assert d["vdc"]["name"] == "Dev"
        assert d["vdc"]["provider_vdc_name"] == "pvdc-01"

    def test_to_template_dict_excludes_none_backend_key(self):
        config = TerraformConfig()
        d = config.to_template_dict()
        # BackendConfig.key defaults to None, should be excluded
        assert "key" not in d["backend"]

    def test_to_template_dict_with_edge(self):
        config = TerraformConfig(
            org=OrgConfig(name="Acme"),
            vdc=VdcConfig(name="Dev", provider_vdc_name="pvdc-01"),
            edge=EdgeGatewayConfig(
                name="gw-01",
                external_network_name="ext-net",
                subnet=EdgeSubnetConfig(
                    gateway="10.0.0.1",
                    prefix_length=24,
                    primary_ip="10.0.0.1",
                ),
            ),
        )
        d = config.to_template_dict()
        assert d["edge"]["name"] == "gw-01"
        assert d["edge"]["external_network_name"] == "ext-net"
        assert d["edge"]["subnet"]["gateway"] == "10.0.0.1"
        # None fields should be excluded
        assert "description" not in d["edge"]

    def test_to_template_dict_without_edge(self):
        config = TerraformConfig(org=OrgConfig(name="Acme"))
        d = config.to_template_dict()
        assert "edge" not in d


# -----------------------------------------------------------------------
#  EdgeGatewayConfig
# -----------------------------------------------------------------------


class TestEdgeSubnetConfig:
    def test_valid_subnet(self):
        subnet = EdgeSubnetConfig(
            gateway="10.0.0.1",
            prefix_length=24,
            primary_ip="10.0.0.1",
        )
        assert subnet.gateway == "10.0.0.1"
        assert subnet.prefix_length == 24

    def test_invalid_gateway_ip_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EdgeSubnetConfig(
                gateway="not-an-ip",
                primary_ip="10.0.0.1",
            )
        assert "valid IP address" in str(exc_info.value)

    def test_invalid_primary_ip_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EdgeSubnetConfig(
                gateway="10.0.0.1",
                primary_ip="999.999.999.999",
            )
        assert "valid IP address" in str(exc_info.value)

    def test_invalid_start_address_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EdgeSubnetConfig(
                gateway="10.0.0.1",
                primary_ip="10.0.0.1",
                start_address="abc",
                end_address="10.0.0.50",
            )
        assert "valid IP address" in str(exc_info.value)

    def test_invalid_end_address_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EdgeSubnetConfig(
                gateway="10.0.0.1",
                primary_ip="10.0.0.1",
                start_address="10.0.0.10",
                end_address="not-ip",
            )
        assert "valid IP address" in str(exc_info.value)

    def test_ip_pool_must_be_paired(self):
        """start_address without end_address must fail."""
        with pytest.raises(ValidationError) as exc_info:
            EdgeSubnetConfig(
                gateway="10.0.0.1",
                primary_ip="10.0.0.1",
                start_address="10.0.0.10",
            )
        assert "both be provided" in str(exc_info.value)

    def test_ip_pool_both_none_ok(self):
        subnet = EdgeSubnetConfig(
            gateway="10.0.0.1",
            primary_ip="10.0.0.1",
        )
        assert subnet.start_address is None
        assert subnet.end_address is None

    def test_ip_pool_both_set_ok(self):
        subnet = EdgeSubnetConfig(
            gateway="10.0.0.1",
            primary_ip="10.0.0.1",
            start_address="10.0.0.10",
            end_address="10.0.0.50",
        )
        assert subnet.start_address == "10.0.0.10"
        assert subnet.end_address == "10.0.0.50"

    def test_prefix_length_default(self):
        subnet = EdgeSubnetConfig(gateway="10.0.0.1", primary_ip="10.0.0.1")
        assert subnet.prefix_length == 24

    def test_prefix_length_negative_rejected(self):
        with pytest.raises(ValidationError):
            EdgeSubnetConfig(
                gateway="10.0.0.1",
                primary_ip="10.0.0.1",
                prefix_length=-1,
            )

    def test_ipv6_accepted(self):
        subnet = EdgeSubnetConfig(
            gateway="2001:db8::1",
            primary_ip="2001:db8::1",
            prefix_length=64,
        )
        assert subnet.gateway == "2001:db8::1"


class TestEdgeGatewayConfig:
    def _make_subnet(self, **overrides):
        defaults = {"gateway": "10.0.0.1", "prefix_length": 24, "primary_ip": "10.0.0.1"}
        defaults.update(overrides)
        return EdgeSubnetConfig(**defaults)

    def test_valid_edge(self):
        edge = EdgeGatewayConfig(
            name="gw-01",
            external_network_name="ext-net",
            subnet=self._make_subnet(),
        )
        assert edge.name == "gw-01"
        assert edge.dedicate_external_network is False

    def test_edge_name_validated(self):
        with pytest.raises(ValidationError) as exc_info:
            EdgeGatewayConfig(
                name="../../evil",
                external_network_name="ext",
                subnet=self._make_subnet(),
            )
        assert "invalid characters" in str(exc_info.value)

    def test_edge_name_stripped(self):
        edge = EdgeGatewayConfig(
            name="  gw-01  ",
            external_network_name="ext",
            subnet=self._make_subnet(),
        )
        assert edge.name == "gw-01"

    def test_edge_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            EdgeGatewayConfig(
                name="",
                external_network_name="ext",
                subnet=self._make_subnet(),
            )

    def test_edge_missing_external_network_rejected(self):
        with pytest.raises(ValidationError):
            EdgeGatewayConfig(name="gw-01", subnet=self._make_subnet())

    def test_edge_missing_subnet_rejected(self):
        with pytest.raises(ValidationError):
            EdgeGatewayConfig(name="gw-01", external_network_name="ext")

    def test_edge_defaults(self):
        edge = EdgeGatewayConfig(
            name="gw-01",
            external_network_name="ext",
            subnet=self._make_subnet(),
        )
        assert edge.dedicate_external_network is False
        assert edge.description is None

    def test_edge_with_all_fields(self):
        edge = EdgeGatewayConfig(
            name="gw-01",
            external_network_name="ext-net",
            subnet=self._make_subnet(
                start_address="10.0.0.10",
                end_address="10.0.0.50",
            ),
            dedicate_external_network=True,
            description="Production edge",
        )
        assert edge.subnet.start_address == "10.0.0.10"
        assert edge.dedicate_external_network is True
        assert edge.description == "Production edge"


# -----------------------------------------------------------------------
#  TerraformDestroyRequest
# -----------------------------------------------------------------------


class TestTerraformDestroyRequest:
    def test_valid_destroy(self):
        req = TerraformDestroyRequest(target_org="Acme")
        assert req.target_org == "Acme"

    def test_destroy_org_with_slashes_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            TerraformDestroyRequest(target_org="../evil")
        assert "invalid characters" in str(exc_info.value)
