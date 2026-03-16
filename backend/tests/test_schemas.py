"""Tests for app.schemas.terraform — Pydantic validation and safe name checks."""

import pytest
from pydantic import ValidationError

from app.schemas.terraform import (
    EdgeGatewayConfig,
    EdgeSubnetConfig,
    NetworkStaticPoolConfig,
    OrgConfig,
    RoutedNetworkConfig,
    TerraformConfig,
    TerraformDestroyRequest,
    VappConfig,
    VappVmConfig,
    VdcConfig,
    VmNetworkConfig,
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

    def test_to_template_dict_with_network(self):
        config = TerraformConfig(
            org=OrgConfig(name="Acme"),
            network=RoutedNetworkConfig(name="net-01", gateway="192.168.1.1"),
        )
        d = config.to_template_dict()
        assert d["network"]["name"] == "net-01"
        assert d["network"]["gateway"] == "192.168.1.1"
        # None fields should be excluded
        assert "dns1" not in d["network"]

    def test_to_template_dict_without_network(self):
        config = TerraformConfig(org=OrgConfig(name="Acme"))
        d = config.to_template_dict()
        assert "network" not in d

    def test_to_template_dict_with_vapp(self):
        config = TerraformConfig(
            org=OrgConfig(name="Acme"),
            vapp=VappConfig(name="my-app"),
        )
        d = config.to_template_dict()
        assert d["vapp"]["name"] == "my-app"
        assert d["vapp"]["power_on"] is False

    def test_to_template_dict_without_vapp(self):
        config = TerraformConfig(org=OrgConfig(name="Acme"))
        d = config.to_template_dict()
        assert "vapp" not in d

    def test_to_template_dict_with_vm(self):
        config = TerraformConfig(
            org=OrgConfig(name="Acme"),
            vm=VappVmConfig(
                name="web-01",
                computer_name="web01",
                catalog_name="my-catalog",
                template_name="ubuntu-22",
            ),
        )
        d = config.to_template_dict()
        assert d["vm"]["name"] == "web-01"
        assert d["vm"]["computer_name"] == "web01"
        assert d["vm"]["catalog_name"] == "my-catalog"
        assert d["vm"]["template_name"] == "ubuntu-22"
        assert d["vm"]["memory"] == 1024
        assert d["vm"]["cpus"] == 1
        assert d["vm"]["power_on"] is True
        # None fields excluded
        assert "storage_profile" not in d["vm"]
        assert "description" not in d["vm"]
        assert "network" not in d["vm"]

    def test_to_template_dict_without_vm(self):
        config = TerraformConfig(org=OrgConfig(name="Acme"))
        d = config.to_template_dict()
        assert "vm" not in d


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
#  NetworkStaticPoolConfig
# -----------------------------------------------------------------------


class TestNetworkStaticPoolConfig:
    def test_valid_pool(self):
        pool = NetworkStaticPoolConfig(
            start_address="192.168.1.10",
            end_address="192.168.1.50",
        )
        assert pool.start_address == "192.168.1.10"
        assert pool.end_address == "192.168.1.50"

    def test_invalid_start_address_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            NetworkStaticPoolConfig(start_address="not-an-ip", end_address="192.168.1.50")
        assert "valid IP address" in str(exc_info.value)

    def test_invalid_end_address_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            NetworkStaticPoolConfig(start_address="192.168.1.10", end_address="abc")
        assert "valid IP address" in str(exc_info.value)

    def test_empty_start_address_rejected(self):
        with pytest.raises(ValidationError):
            NetworkStaticPoolConfig(start_address="", end_address="192.168.1.50")

    def test_empty_end_address_rejected(self):
        with pytest.raises(ValidationError):
            NetworkStaticPoolConfig(start_address="192.168.1.10", end_address="")


# -----------------------------------------------------------------------
#  RoutedNetworkConfig
# -----------------------------------------------------------------------


class TestRoutedNetworkConfig:
    def test_valid_network(self):
        net = RoutedNetworkConfig(name="net-01", gateway="192.168.1.1")
        assert net.name == "net-01"
        assert net.gateway == "192.168.1.1"
        assert net.prefix_length == 24

    def test_name_validated_with_safe_name(self):
        with pytest.raises(ValidationError) as exc_info:
            RoutedNetworkConfig(name="../../evil", gateway="192.168.1.1")
        assert "invalid characters" in str(exc_info.value)

    def test_name_stripped(self):
        net = RoutedNetworkConfig(name="  net-01  ", gateway="192.168.1.1")
        assert net.name == "net-01"

    def test_invalid_gateway_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            RoutedNetworkConfig(name="net-01", gateway="not-an-ip")
        assert "valid IP address" in str(exc_info.value)

    def test_dns1_validated_when_set(self):
        net = RoutedNetworkConfig(name="net-01", gateway="192.168.1.1", dns1="8.8.8.8")
        assert net.dns1 == "8.8.8.8"

    def test_invalid_dns1_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            RoutedNetworkConfig(name="net-01", gateway="192.168.1.1", dns1="bad")
        assert "valid IP address" in str(exc_info.value)

    def test_dns2_validated_when_set(self):
        net = RoutedNetworkConfig(name="net-01", gateway="192.168.1.1", dns2="8.8.4.4")
        assert net.dns2 == "8.8.4.4"

    def test_invalid_dns2_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            RoutedNetworkConfig(name="net-01", gateway="192.168.1.1", dns2="bad")
        assert "valid IP address" in str(exc_info.value)

    def test_defaults(self):
        net = RoutedNetworkConfig(name="net-01", gateway="192.168.1.1")
        assert net.prefix_length == 24
        assert net.dns1 is None
        assert net.dns2 is None
        assert net.static_ip_pool is None
        assert net.description is None

    def test_all_fields(self):
        net = RoutedNetworkConfig(
            name="net-01",
            gateway="192.168.1.1",
            prefix_length=28,
            dns1="8.8.8.8",
            dns2="8.8.4.4",
            static_ip_pool=NetworkStaticPoolConfig(
                start_address="192.168.1.10",
                end_address="192.168.1.50",
            ),
            description="Production network",
        )
        assert net.prefix_length == 28
        assert net.dns1 == "8.8.8.8"
        assert net.static_ip_pool.start_address == "192.168.1.10"
        assert net.description == "Production network"

    def test_prefix_length_negative_rejected(self):
        with pytest.raises(ValidationError):
            RoutedNetworkConfig(name="net-01", gateway="192.168.1.1", prefix_length=-1)

    def test_prefix_length_over_128_rejected(self):
        with pytest.raises(ValidationError):
            RoutedNetworkConfig(name="net-01", gateway="192.168.1.1", prefix_length=129)


# -----------------------------------------------------------------------
#  VappConfig
# -----------------------------------------------------------------------


class TestVappConfig:
    def test_valid_vapp_minimal(self):
        vapp = VappConfig(name="my-app")
        assert vapp.name == "my-app"
        assert vapp.power_on is False
        assert vapp.description is None

    def test_name_validated_with_safe_name(self):
        with pytest.raises(ValidationError) as exc_info:
            VappConfig(name="../../evil")
        assert "invalid characters" in str(exc_info.value)

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            VappConfig(name="")

    def test_name_stripped(self):
        vapp = VappConfig(name="  my-app  ")
        assert vapp.name == "my-app"

    def test_defaults(self):
        vapp = VappConfig(name="app")
        assert vapp.power_on is False
        assert vapp.description is None

    def test_all_fields(self):
        vapp = VappConfig(
            name="web-app",
            description="Production vApp",
            power_on=True,
        )
        assert vapp.name == "web-app"
        assert vapp.description == "Production vApp"
        assert vapp.power_on is True


# -----------------------------------------------------------------------
#  VmNetworkConfig
# -----------------------------------------------------------------------


class TestVmNetworkConfig:
    def test_valid_minimal(self):
        net = VmNetworkConfig(name="net-01")
        assert net.name == "net-01"
        assert net.type == "org"
        assert net.ip_allocation_mode == "POOL"
        assert net.ip is None

    def test_default_pool(self):
        net = VmNetworkConfig(name="net-01")
        assert net.ip_allocation_mode == "POOL"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            VmNetworkConfig(name="net-01", ip_allocation_mode="STATIC")
        assert "POOL" in str(exc_info.value) or "ip_allocation_mode" in str(exc_info.value)

    def test_manual_without_ip_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            VmNetworkConfig(name="net-01", ip_allocation_mode="MANUAL")
        assert "ip is required" in str(exc_info.value)

    def test_manual_with_ip_ok(self):
        net = VmNetworkConfig(name="net-01", ip_allocation_mode="MANUAL", ip="10.0.0.5")
        assert net.ip == "10.0.0.5"

    def test_pool_ip_none_ok(self):
        net = VmNetworkConfig(name="net-01", ip_allocation_mode="POOL")
        assert net.ip is None

    def test_invalid_ip_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            VmNetworkConfig(name="net-01", ip_allocation_mode="MANUAL", ip="not-an-ip")
        assert "valid IP address" in str(exc_info.value)

    def test_name_safe_name(self):
        with pytest.raises(ValidationError) as exc_info:
            VmNetworkConfig(name="../../evil")
        assert "invalid characters" in str(exc_info.value)

    def test_dhcp_mode_ok(self):
        net = VmNetworkConfig(name="net-01", ip_allocation_mode="DHCP")
        assert net.ip_allocation_mode == "DHCP"
        assert net.ip is None


# -----------------------------------------------------------------------
#  VappVmConfig
# -----------------------------------------------------------------------


class TestVappVmConfig:
    def test_valid_minimal(self):
        vm = VappVmConfig(
            name="web-01",
            computer_name="web01",
            catalog_name="my-catalog",
            template_name="ubuntu-22",
        )
        assert vm.name == "web-01"
        assert vm.computer_name == "web01"
        assert vm.catalog_name == "my-catalog"
        assert vm.template_name == "ubuntu-22"

    def test_all_names_validated(self):
        """All name fields go through _validate_safe_name."""
        for field in ["name", "computer_name", "catalog_name", "template_name"]:
            with pytest.raises(ValidationError) as exc_info:
                VappVmConfig(
                    **{
                        "name": "ok",
                        "computer_name": "ok",
                        "catalog_name": "ok",
                        "template_name": "ok",
                        field: "../../evil",
                    }
                )
            assert "invalid characters" in str(exc_info.value)

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            VappVmConfig(
                name="",
                computer_name="ok",
                catalog_name="ok",
                template_name="ok",
            )

    def test_defaults(self):
        vm = VappVmConfig(
            name="vm-01",
            computer_name="vm01",
            catalog_name="cat",
            template_name="tpl",
        )
        assert vm.memory == 1024
        assert vm.cpus == 1
        assert vm.cpu_cores == 1
        assert vm.power_on is True
        assert vm.storage_profile is None
        assert vm.network is None
        assert vm.description is None

    def test_memory_below_256_rejected(self):
        with pytest.raises(ValidationError):
            VappVmConfig(
                name="vm",
                computer_name="vm",
                catalog_name="c",
                template_name="t",
                memory=128,
            )

    def test_cpus_below_1_rejected(self):
        with pytest.raises(ValidationError):
            VappVmConfig(
                name="vm",
                computer_name="vm",
                catalog_name="c",
                template_name="t",
                cpus=0,
            )

    def test_cpu_cores_below_1_rejected(self):
        with pytest.raises(ValidationError):
            VappVmConfig(
                name="vm",
                computer_name="vm",
                catalog_name="c",
                template_name="t",
                cpu_cores=0,
            )

    def test_all_fields_filled(self):
        vm = VappVmConfig(
            name="web-01",
            computer_name="web01",
            catalog_name="my-catalog",
            template_name="ubuntu-22",
            memory=2048,
            cpus=4,
            cpu_cores=2,
            storage_profile="Gold",
            network=VmNetworkConfig(name="net-01", ip_allocation_mode="MANUAL", ip="10.0.0.5"),
            power_on=False,
            description="Production VM",
        )
        assert vm.memory == 2048
        assert vm.cpus == 4
        assert vm.cpu_cores == 2
        assert vm.storage_profile == "Gold"
        assert vm.network.ip == "10.0.0.5"
        assert vm.power_on is False
        assert vm.description == "Production VM"

    def test_network_none_ok(self):
        vm = VappVmConfig(
            name="vm",
            computer_name="vm",
            catalog_name="c",
            template_name="t",
        )
        assert vm.network is None

    def test_computer_name_max_63(self):
        vm = VappVmConfig(
            name="vm",
            computer_name="a" * 63,
            catalog_name="c",
            template_name="t",
        )
        assert len(vm.computer_name) == 63

    def test_computer_name_over_63_rejected(self):
        with pytest.raises(ValidationError):
            VappVmConfig(
                name="vm",
                computer_name="a" * 64,
                catalog_name="c",
                template_name="t",
            )


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
