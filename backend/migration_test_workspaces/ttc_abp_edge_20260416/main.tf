variable "vcd_url" {
  type = string
}
variable "vcd_user" {
  type      = string
  sensitive = true
}
variable "vcd_password" {
  type      = string
  sensitive = true
}
variable "target_org" {
  type    = string
  default = "TTC"
}
variable "target_vdc" {
  type    = string
  default = "test-vdc-01"
}
variable "target_edge_id" {
  type    = string
  default = "urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271"
}
resource "vcd_nsxt_ip_set" "ipset_3465e8c8" {
  org             = var.target_org
  edge_gateway_id = var.target_edge_id
  name            = "ipset_internal"
  description     = "Migrated from VCD 10.4, used by rules: 137250"
  ip_addresses    = ["10.127.28.0/28", "10.127.28.64/28", "10.255.255.248/30"]
}
resource "vcd_nsxt_ip_set" "ipset_ca0f9ebc" {
  org             = var.target_org
  edge_gateway_id = var.target_edge_id
  name            = "ipset_ca0f9ebc"
  description     = "Migrated from VCD 10.4, used by rules: 137250"
  ip_addresses    = ["10.127.28.1", "10.127.28.65", "10.255.255.249", "172.20.10.84"]
}
resource "vcd_nsxt_ip_set" "ipset_623dc243" {
  org             = var.target_org
  edge_gateway_id = var.target_edge_id
  name            = "ipset_623dc243"
  description     = "Migrated from VCD 10.4, used by rules: 133145"
  ip_addresses    = ["10.157.52.0/27", "10.40.40.0/24", "172.20.10.83/32", "172.20.7.60/30"]
}
resource "vcd_nsxt_ip_set" "ipset_f31b6dfc" {
  org             = var.target_org
  edge_gateway_id = var.target_edge_id
  name            = "ipset_f31b6dfc"
  description     = "Migrated from VCD 10.4, used by rules: 137251"
  ip_addresses    = ["172.20.10.83/32"]
}
data "vcd_nsxt_app_port_profile" "udp_53" {
  name  = "DNS-UDP"
  scope = "SYSTEM"
}
data "vcd_nsxt_app_port_profile" "tcp_53" {
  name  = "DNS"
  scope = "SYSTEM"
}
resource "vcd_nsxt_firewall" "migrated" {
  org             = var.target_org
  edge_gateway_id = var.target_edge_id
  rule {
    name        = "migrated_137250_dns"
    direction   = "IN_OUT"
    ip_protocol = "IPV4"
    action      = "ALLOW"
    enabled     = true
    logging     = false
    source_ids  = [vcd_nsxt_ip_set.ipset_3465e8c8.id]
    destination_ids = [vcd_nsxt_ip_set.ipset_ca0f9ebc.id]
    app_port_profile_ids = [
      data.vcd_nsxt_app_port_profile.udp_53.id,
      data.vcd_nsxt_app_port_profile.tcp_53.id,
    ]
  }
  rule {
    name        = "migrated_rule_133145"
    direction   = "IN_OUT"
    ip_protocol = "IPV4"
    action      = "ALLOW"
    enabled     = true
    logging     = false
    source_ids  = [vcd_nsxt_ip_set.ipset_623dc243.id]
  }
  rule {
    name        = "migrated_rule_137251"
    direction   = "IN_OUT"
    ip_protocol = "IPV4"
    action      = "ALLOW"
    enabled     = true
    logging     = false
    destination_ids = [vcd_nsxt_ip_set.ipset_f31b6dfc.id]
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_1" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_1"
  description     = ""
  network_cidr    = "10.40.40.0/24"
  next_hop {
    ip_address     = "172.20.7.61"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_2" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_2"
  description     = ""
  network_cidr    = "10.121.42.0/24"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_3" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_3"
  description     = ""
  network_cidr    = "10.155.12.0/24"
  next_hop {
    ip_address     = "172.20.7.61"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_4" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_4"
  description     = ""
  network_cidr    = "10.157.20.0/27"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_5" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_5"
  description     = ""
  network_cidr    = "10.157.28.0/27"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_6" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_6"
  description     = ""
  network_cidr    = "10.157.36.0/27"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_7" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_7"
  description     = ""
  network_cidr    = "10.157.44.0/27"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_8" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_8"
  description     = ""
  network_cidr    = "10.157.52.0/27"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_9" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_9"
  description     = ""
  network_cidr    = "10.157.60.0/27"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_10" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_10"
  description     = ""
  network_cidr    = "10.157.68.0/27"
  next_hop {
    ip_address     = "172.22.0.1"
    admin_distance = 1
  }
}
resource "vcd_nsxt_edgegateway_static_route" "route_11" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_11"
  description     = ""
  network_cidr    = "172.20.10.72/29"
  next_hop {
    ip_address     = "172.20.10.83"
    admin_distance = 1
  }
}
