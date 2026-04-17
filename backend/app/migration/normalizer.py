"""XML → canonical JSON normalizer for NSX-V edge gateway migration.

Parses raw XML from legacy VCD 10.4 NSX-V endpoints and converts them
into a stable canonical JSON structure that the HCL generator depends on.

Pure functions, no I/O, no side effects.
"""

import logging
from datetime import datetime, timezone
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

logger = logging.getLogger(__name__)

SYSTEM_PROFILES: dict[str, str] = {}  # All profiles created as TENANT-scope resources

_ACTION_MAP = {
    "accept": "ALLOW",
    "deny": "DROP",
}

_SYSTEM_RULE_TYPES = {"default_policy"}


def _normalize_action(action: str) -> str:
    """Map NSX-V action to canonical form: accept→ALLOW, deny→DROP."""
    return _ACTION_MAP.get(action.lower(), action.upper())


def _classify_rule_type(rule_type: str) -> bool:
    """Return True if the rule type is a system rule (should be skipped in HCL)."""
    return rule_type.lower() in _SYSTEM_RULE_TYPES


def _build_app_port_profile_key(protocol: str, port: str) -> str:
    """Build a dedup key like 'tcp_443' or 'udp_9000-10999'."""
    return f"{protocol.lower()}_{port}"


def _resolve_system_profile(key: str) -> str | None:
    """Look up a known system-defined app port profile name, or None."""
    return SYSTEM_PROFILES.get(key)


def _text(el: Element | None, tag: str, default: str = "") -> str:
    """Extract text from a child element, or return default."""
    if el is None:
        return default
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return default


def _bool(el: Element | None, tag: str, default: bool = False) -> bool:
    """Extract boolean from a child element text."""
    return _text(el, tag).lower() == "true" if _text(el, tag) else default


def _parse_endpoint(el: Element | None) -> dict:
    """Parse a firewall source or destination element."""
    result: dict = {
        "ip_addresses": [],
        "grouping_object_ids": [],
        "vnic_group_ids": [],
        "exclude": False,
    }
    if el is None:
        return result

    result["exclude"] = _text(el, "exclude").lower() == "true"

    for ip_el in el.findall("ipAddress"):
        if ip_el.text:
            result["ip_addresses"].append(ip_el.text.strip())

    for gid_el in el.findall("groupingObjectId"):
        if gid_el.text:
            result["grouping_object_ids"].append(gid_el.text.strip())

    for vnic_el in el.findall("vnicGroupId"):
        if vnic_el.text:
            result["vnic_group_ids"].append(vnic_el.text.strip())

    return result


def _has_vse_vnic(rule_el: Element) -> bool:
    """Check if a firewall rule has a vnicGroupId containing 'vse'."""
    for endpoint_tag in ("source", "destination"):
        endpoint = rule_el.find(endpoint_tag)
        if endpoint is None:
            continue
        for vnic_el in endpoint.findall("vnicGroupId"):
            if vnic_el.text and "vse" in vnic_el.text.lower():
                return True
    return False


def _parse_application_services(app_el: Element | None) -> list[dict[str, str]]:
    """Extract protocol/port pairs from a firewall application element."""
    if app_el is None:
        return []
    services: list[dict[str, str]] = []
    for svc in app_el.findall("service"):
        protocol = _text(svc, "protocol")
        port = _text(svc, "port")
        if protocol:
            entry: dict[str, str] = {"protocol": protocol}
            if port:
                entry["port"] = port
            services.append(entry)
    return services


def _normalize_firewall(xml_str: str) -> dict:
    """Parse firewall XML into canonical structure."""
    root = ET.fromstring(xml_str)

    enabled = _bool(root, "enabled")

    default_policy = root.find("defaultPolicy")
    default_action_source = _normalize_action(
        _text(default_policy, "action", "accept")
    )

    rules = []
    rules_container = root.find("firewallRules")
    if rules_container is None:
        return {
            "enabled": enabled,
            "default_action_source": default_action_source,
            "default_action_target": None,
            "rules": [],
        }

    for rule_el in rules_container.findall("firewallRule"):
        if _has_vse_vnic(rule_el):
            logger.debug(
                "Skipping firewall rule id=%s (vse vnicGroupId)",
                _text(rule_el, "id"),
            )
            continue

        rule_type = _text(rule_el, "ruleType", "user")
        source = _parse_endpoint(rule_el.find("source"))
        destination = _parse_endpoint(rule_el.find("destination"))
        application = _parse_application_services(rule_el.find("application"))

        rules.append({
            "original_id": _text(rule_el, "id"),
            "name": _text(rule_el, "name"),
            "rule_type": rule_type,
            "is_system": _classify_rule_type(rule_type),
            "enabled": _bool(rule_el, "enabled"),
            "action": _normalize_action(_text(rule_el, "action", "accept")),
            "logging": _bool(rule_el, "loggingEnabled"),
            "source": source,
            "destination": destination,
            "application": application,
        })

    return {
        "enabled": enabled,
        "default_action_source": default_action_source,
        "default_action_target": None,
        "rules": rules,
    }


def _normalize_nat(xml_str: str) -> dict:
    """Parse NAT XML into canonical structure with deduped app port profiles."""
    root = ET.fromstring(xml_str)

    enabled = _bool(root, "enabled")
    rules = []
    profiles: dict[str, dict] = {}  # key → profile dict

    rules_container = root.find("natRules")
    if rules_container is None:
        return {
            "enabled": enabled,
            "rules": [],
            "required_app_port_profiles": [],
        }

    for rule_el in rules_container.findall("natRule"):
        rule_id = _text(rule_el, "ruleId")
        action = _text(rule_el, "action", "").upper()
        protocol = _text(rule_el, "protocol", "any")
        original_port = _text(rule_el, "originalPort", "")
        translated_port = _text(rule_el, "translatedPort", "")

        needs_profile = (
            protocol.lower() not in ("any", "")
            and original_port
            and original_port.lower() != "any"
        )

        app_port_profile_key = ""
        if needs_profile:
            app_port_profile_key = _build_app_port_profile_key(protocol, original_port)
            if app_port_profile_key not in profiles:
                system_name = _resolve_system_profile(app_port_profile_key)
                is_system = system_name is not None
                custom_name = (
                    None
                    if is_system
                    else f"ttc_nat_{protocol.lower()}_{original_port.replace('-', '_')}"
                )
                profiles[app_port_profile_key] = {
                    "key": app_port_profile_key,
                    "protocol": protocol.upper(),
                    "ports": original_port,
                    "is_system_defined": is_system,
                    "system_defined_name": system_name,
                    "custom_name": custom_name,
                    "used_by_rule_ids": [],
                }
            profiles[app_port_profile_key]["used_by_rule_ids"].append(rule_id)

        rules.append({
            "original_id": rule_id,
            "action": action,
            "description": _text(rule_el, "description"),
            "enabled": _bool(rule_el, "enabled"),
            "logging": _bool(rule_el, "loggingEnabled"),
            "original_address": _text(rule_el, "originalAddress"),
            "translated_address": _text(rule_el, "translatedAddress"),
            "original_port": original_port,
            "translated_port": translated_port,
            "protocol": protocol,
            "needs_app_port_profile": needs_profile,
            "app_port_profile_key": app_port_profile_key,
        })

    return {
        "enabled": enabled,
        "rules": rules,
        "required_app_port_profiles": list(profiles.values()),
    }


def _normalize_routing(xml_str: str) -> dict:
    """Parse routing XML into canonical static routes (skip default route, strip vnic)."""
    root = ET.fromstring(xml_str)

    static_routes = []
    static_routing = root.find("staticRouting")
    if static_routing is None:
        return {"static_routes": []}

    routes_container = static_routing.find("staticRoutes")
    if routes_container is None:
        return {"static_routes": []}

    for route_el in routes_container.findall("route"):
        network = _text(route_el, "network")

        if network == "0.0.0.0/0":
            logger.debug("Skipping default route 0.0.0.0/0")
            continue

        admin_distance_str = _text(route_el, "adminDistance", "1")
        try:
            admin_distance = int(admin_distance_str)
        except ValueError:
            logger.warning(
                "Invalid adminDistance=%s for route %s, using default 1",
                admin_distance_str, network,
            )
            admin_distance = 1

        mtu_str = _text(route_el, "mtu", "1500")
        try:
            mtu = int(mtu_str)
        except ValueError:
            logger.warning(
                "Invalid mtu=%s for route %s, using default 1500",
                mtu_str, network,
            )
            mtu = 1500

        static_routes.append({
            "network": network,
            "next_hop": _text(route_el, "nextHop"),
            "mtu": mtu,
            "description": _text(route_el, "description"),
            "admin_distance": admin_distance,
        })

    return {"static_routes": static_routes}


def _normalize_edge_metadata(xml_str: str) -> dict:
    """Parse edge gateway metadata XML (name, interfaces, backing type)."""
    root = ET.fromstring(xml_str)

    ns = ""
    tag = root.tag
    if "}" in tag:
        ns = tag.split("}")[0] + "}"

    name = root.get("name", "")

    config = root.find(f"{ns}Configuration")
    backing_type = ""
    interfaces = []

    if config is not None:
        backing_type = _text(config, f"{ns}GatewayBackingType")

        gw_interfaces = config.find(f"{ns}GatewayInterfaces")
        if gw_interfaces is not None:
            for iface_el in gw_interfaces.findall(f"{ns}GatewayInterface"):
                iface_name = _text(iface_el, f"{ns}Name")
                iface_type = _text(iface_el, f"{ns}InterfaceType")

                subnets = []
                for subnet_el in iface_el.findall(f"{ns}SubnetParticipation"):
                    subnets.append({
                        "gateway": _text(subnet_el, f"{ns}Gateway"),
                        "netmask": _text(subnet_el, f"{ns}Netmask"),
                        "ip_address": _text(subnet_el, f"{ns}IpAddress"),
                    })

                interfaces.append({
                    "name": iface_name,
                    "type": iface_type,
                    "subnets": subnets,
                })

    return {
        "name": name,
        "interfaces": interfaces,
        "backing_type": backing_type,
    }


def normalize_edge_snapshot(raw_xmls: dict[str, str]) -> dict:
    """Parse raw XML strings into canonical migration JSON.

    Args:
        raw_xmls: dict with keys:
            - "edge_metadata.xml" -- edge gateway XML
            - "firewall_config.xml" -- firewall config XML
            - "nat_config.xml" -- NAT config XML
            - "routing_config.xml" -- routing config XML

    Returns:
        Canonical JSON dict matching schema_version=1

    Raises:
        ValueError: If required XML keys are missing from raw_xmls.
    """
    required_keys = {
        "edge_metadata.xml",
        "firewall_config.xml",
        "nat_config.xml",
        "routing_config.xml",
    }
    missing = required_keys - raw_xmls.keys()
    if missing:
        raise ValueError(f"Missing required XML keys: {missing}")

    edge_meta = _normalize_edge_metadata(raw_xmls["edge_metadata.xml"])
    firewall = _normalize_firewall(raw_xmls["firewall_config.xml"])
    nat = _normalize_nat(raw_xmls["nat_config.xml"])
    routing = _normalize_routing(raw_xmls["routing_config.xml"])

    return {
        "schema_version": 1,
        "source": {
            "edge_name": edge_meta["name"],
            "backing_type": edge_meta["backing_type"],
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
        },
        "edge": edge_meta,
        "firewall": firewall,
        "nat": nat,
        "routing": routing,
    }
