resource "vcd_org" "test_org" {
  name             = "test-org"
  full_name        = "Test Organization"
  is_enabled       = true
  delete_force     = true
  delete_recursive = true
}

resource "vcd_org_vdc" "test_vdc" {
  name              = "test-vdc"
  org               = vcd_org.test_org.name
  allocation_model  = "Flex"
  network_pool_name = "ALM-GENEVE-LAG"
  provider_vdc_name = "comp-alm-dell-01-pvdc"

  elasticity                 = false
  include_vm_memory_overhead = true

  compute_capacity {
    cpu {
      allocated = 5000
      limit     = 5000
    }
    memory {
      allocated = 16384
      limit     = 16384
    }
  }

  storage_profile {
    name    = "alm-fas8300-ssd-01"
    limit   = 51200
    default = true
    enabled = true
  }

  enabled                  = true
  enable_thin_provisioning = true
  enable_fast_provisioning = false
  delete_force             = true
  delete_recursive         = true
}

resource "vcd_vapp" "test_vapp" {
  name     = "test-vapp"
  org      = vcd_org.test_org.name
  vdc      = vcd_org_vdc.test_vdc.name
  power_on = false
}
