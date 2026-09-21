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



# ---------------------------------------------------------------------------
#  IPsec VPN
# ---------------------------------------------------------------------------

# NSX-V value -> NSX-T value, built from every value present across all
# tunnels on the legacy VCD rather than from a sample. Anything absent has
# no NSX-T equivalent: the tunnel is reported as not migratable instead of
# being given a plausible default, because a wrong algorithm produces a
# tunnel that silently never establishes.
NSXV_TO_NSXT: dict[str, dict[str, str]] = {
    "encryptionAlgorithm": {
        "aes": "AES_128",
        "aes256": "AES_256",
        "aes-gcm": "AES_GCM_128",
        # 3DES is deliberately absent — NSX-T removed it.
    },
    "digestAlgorithm": {
        "sha1": "SHA1",
        "sha-256": "SHA2_256",
        "sha-384": "SHA2_384",
        "sha-512": "SHA2_512",
    },
    "dhGroup": {
        "dh2": "GROUP2",
        "dh5": "GROUP5",
        "dh14": "GROUP14",
        "dh15": "GROUP15",
        "dh16": "GROUP16",
        "dh19": "GROUP19",
        "dh20": "GROUP20",
        "dh21": "GROUP21",
    },
    "ikeVersion": {
        "ikev1": "IKE_V1",
        "ikev2": "IKE_V2",
        # Hyphenated on the wire; "ikeflex" would not match.
        "ike-flex": "IKE_FLEX",
    },
}

_ANY_PEER = {"any", "0.0.0.0", ""}


def _map_value(field: str, raw: str, unsupported: list[str]) -> str | None:
    """Translate one crypto value, recording a refusal when it has no match."""
    key = (raw or "").strip().lower()
    if not key:
        unsupported.append(f"{field} is empty")
        return None
    mapped = NSXV_TO_NSXT[field].get(key)
    if mapped is None:
        unsupported.append(f"{field}={key} has no NSX-T equivalent")
    return mapped


def _normalize_ipsec(xml_str: str) -> dict:
    """Parse NSX-V ipsec/config into canonical tunnels.

    Disabled tunnels are kept: the operator migrates them as-is so the
    destination mirrors the source, and they are switched on individually
    during cutover.

    Pre-shared keys travel in this structure but must never reach rendered
    HCL — the generator binds them to TF_VAR_* variables instead.
    """
    root = ET.fromstring(xml_str)

    tunnels: list[dict] = []
    for index, site in enumerate(root.findall(".//site"), start=1):
        unsupported: list[str] = []

        name = _text(site, "name") or _text(site, "siteId") or f"tunnel_{index}"
        local_ip = _text(site, "localIp")
        peer_ip = _text(site, "peerIp")
        local_id = _text(site, "localId")
        peer_id = _text(site, "peerId")

        local_networks = [
            el.text.strip()
            for el in site.findall("localSubnets/subnet")
            if el is not None and el.text
        ]
        remote_networks = [
            el.text.strip()
            for el in site.findall("peerSubnets/subnet")
            if el is not None and el.text
        ]

        if peer_ip.strip().lower() in _ANY_PEER:
            unsupported.append(
                "peer address is ANY — NSX-T requires a concrete remote address"
            )
        if not remote_networks:
            unsupported.append(
                "no remote networks — NSX-T would read this as 0.0.0.0/0"
            )

        auth = (_text(site, "authenticationMode") or "psk").lower()
        if "cert" in auth:
            unsupported.append(
                "certificate authentication — certificates must be pre-loaded "
                "on the destination, they cannot be migrated from here"
            )

        tunnels.append({
            "name": name,
            "enabled": _bool(site, "enabled", True),
            "local_ip": local_ip,
            "peer_ip": peer_ip,
            # NSX-T defaults remote_id to the peer address. Only carry an
            # identity that actually differs — typically a peer behind NAT,
            # where omitting it makes phase 1 fail as an auth error.
            "local_id": local_id if local_id and local_id != local_ip else None,
            "remote_id": peer_id if peer_id and peer_id != peer_ip else None,
            "local_networks": local_networks,
            "remote_networks": remote_networks,
            "encryption": _map_value(
                "encryptionAlgorithm", _text(site, "encryptionAlgorithm"), unsupported
            ),
            "digest": _map_value(
                "digestAlgorithm", _text(site, "digestAlgorithm"), unsupported
            ),
            "dh_group": _map_value("dhGroup", _text(site, "dhGroup"), unsupported),
            "ike_version": _map_value(
                "ikeVersion",
                _text(site, "ikeOption") or _text(site, "ikeVersion"),
                unsupported,
            ),
            "pfs": _bool(site, "enablePfs", True),
            "psk": _text(site, "psk") or None,
            "unsupported": unsupported,
            "migratable": not unsupported,
        })

    if tunnels:
        blocked = [t["name"] for t in tunnels if not t["migratable"]]
        logger.info(
            "ipsec normalized tunnels=%d not_migratable=%d%s",
            len(tunnels), len(blocked),
            f" ({', '.join(blocked)})" if blocked else "",
        )

    return {
        "enabled": _bool(root, "enabled", False),
        "tunnels": tunnels,
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
    # Optional: snapshots captured before IPsec support have four documents.
    ipsec_xml = raw_xmls.get("ipsec_config.xml")
    ipsec = (
        _normalize_ipsec(ipsec_xml)
        if ipsec_xml
        else {"enabled": False, "tunnels": []}
    )

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
        "ipsec": ipsec,
    }
