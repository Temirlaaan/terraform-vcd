import { Copy, Check, Download } from "lucide-react";
import { useState, useMemo } from "react";
import { useConfigStore } from "@/store/useConfigStore";

/* ------------------------------------------------------------------ */
/*  Client-side HCL generator (instant, no backend calls)             */
/* ------------------------------------------------------------------ */

function slug(value: string): string {
  return (
    value
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_|_$/g, "") || "resource"
  );
}

function generateHcl(state: {
  provider: { org: string; allow_unverified_ssl: boolean };
  backend: { bucket: string; endpoint: string; region: string };
  org: { name: string; full_name: string; description: string; is_enabled: boolean; delete_force: boolean; delete_recursive: boolean };
  vdc: { name: string; provider_vdc_name: string; allocation_model: string; network_pool_name: string; cpu_allocated: number; cpu_limit: number; memory_allocated: number; memory_limit: number; storage_profiles: { name: string; limit: number; default: boolean; enabled: boolean }[]; enable_thin_provisioning: boolean; enable_fast_provisioning: boolean; elasticity: boolean; include_vm_memory_overhead: boolean; memory_guaranteed?: number; delete_force: boolean; delete_recursive: boolean; description: string };
  edge: { name: string; external_network_name: string; subnet: { gateway: string; prefix_length: number; primary_ip: string; start_address?: string; end_address?: string }; dedicate_external_network: boolean; description?: string };
  network: { name: string; gateway: string; prefix_length: number; dns1?: string; dns2?: string; static_ip_pool?: { start_address: string; end_address: string }; description?: string };
  vapp: { name: string; description?: string; power_on: boolean };
  vm: { name: string; computer_name: string; catalog_name: string; template_name: string; memory: number; cpus: number; cpu_cores: number; storage_profile?: string; network?: { type: string; name: string; ip_allocation_mode: string; ip?: string }; power_on: boolean; description?: string };
}): string {
  const lines: string[] = [];

  // --- Provider / Backend ---
  lines.push(`terraform {`);
  lines.push(`  required_providers {`);
  lines.push(`    vcd = {`);
  lines.push(`      source  = "vmware/vcd"`);
  lines.push(`      version = "~> 3.12"`);
  lines.push(`    }`);
  lines.push(`    time = {`);
  lines.push(`      source  = "hashicorp/time"`);
  lines.push(`      version = "~> 0.10.0"`);
  lines.push(`    }`);
  lines.push(`  }`);
  lines.push(``);
  lines.push(`  backend "s3" {`);
  lines.push(`    bucket                      = "${state.backend.bucket}"`);
  lines.push(`    key                         = "${slug(state.org.name || "default")}/terraform.tfstate"`);
  lines.push(`    region                      = "${state.backend.region}"`);
  lines.push(`    endpoint                    = "${state.backend.endpoint}"`);
  lines.push(`    skip_credentials_validation  = true`);
  lines.push(`    skip_metadata_api_check      = true`);
  lines.push(`    skip_region_validation       = true`);
  lines.push(`    skip_requesting_account_id   = true`);
  lines.push(`    force_path_style             = true`);
  lines.push(`  }`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`provider "vcd" {`);
  lines.push(`  url                  = var.vcd_url`);
  lines.push(`  user                 = var.vcd_user`);
  lines.push(`  password             = var.vcd_password`);
  lines.push(`  org                  = "${state.provider.org}"`);
  lines.push(`  allow_unverified_ssl = ${state.provider.allow_unverified_ssl}`);
  lines.push(`}`);

  // --- Organization ---
  if (state.org.name) {
    lines.push(``);
    lines.push(`resource "vcd_org" "${slug(state.org.name)}" {`);
    lines.push(`  name             = "${state.org.name}"`);
    lines.push(`  full_name        = "${state.org.full_name || state.org.name}"`);
    lines.push(`  is_enabled       = ${state.org.is_enabled}`);
    lines.push(`  delete_force     = ${state.org.delete_force}`);
    lines.push(`  delete_recursive = ${state.org.delete_recursive}`);
    if (state.org.description) {
      lines.push(`  description      = "${state.org.description}"`);
    }
    lines.push(`}`);
    lines.push(``);
    lines.push(`resource "time_sleep" "wait_for_org" {`);
    lines.push(`  depends_on      = [vcd_org.${slug(state.org.name)}]`);
    lines.push(`  create_duration = "30s"`);
    lines.push(`}`);
  }

  // --- VDC ---
  if (state.vdc.name && state.vdc.provider_vdc_name) {
    lines.push(``);
    lines.push(`resource "vcd_org_vdc" "${slug(state.vdc.name)}" {`);
    lines.push(`  name              = "${state.vdc.name}"`);
    lines.push(`  org               = vcd_org.${slug(state.org.name)}.name`);
    lines.push(`  allocation_model  = "${state.vdc.allocation_model}"`);
    if (state.vdc.network_pool_name) {
      lines.push(`  network_pool_name = "${state.vdc.network_pool_name}"`);
    }
    lines.push(`  provider_vdc_name = "${state.vdc.provider_vdc_name}"`);
    lines.push(``);
    lines.push(`  elasticity                 = ${state.vdc.elasticity}`);
    lines.push(`  include_vm_memory_overhead = ${state.vdc.include_vm_memory_overhead}`);
    if (state.vdc.memory_guaranteed != null) {
      lines.push(`  memory_guaranteed          = ${(state.vdc.memory_guaranteed / 100).toFixed(2)}`);
    }
    lines.push(``);
    lines.push(`  compute_capacity {`);
    lines.push(`    cpu {`);
    lines.push(`      allocated = ${state.vdc.cpu_allocated}`);
    lines.push(`      limit     = ${state.vdc.cpu_limit}`);
    lines.push(`    }`);
    lines.push(``);
    lines.push(`    memory {`);
    lines.push(`      allocated = ${state.vdc.memory_allocated}`);
    lines.push(`      limit     = ${state.vdc.memory_limit}`);
    lines.push(`    }`);
    lines.push(`  }`);
    const filledProfiles = state.vdc.storage_profiles.filter((sp) => sp.name);
    for (const sp of filledProfiles) {
      lines.push(``);
      lines.push(`  storage_profile {`);
      lines.push(`    name    = "${sp.name}"`);
      lines.push(`    limit   = ${sp.limit}`);
      lines.push(`    default = ${sp.default}`);
      lines.push(`    enabled = ${sp.enabled}`);
      lines.push(`  }`);
    }
    lines.push(``);
    lines.push(`  enabled                  = true`);
    lines.push(`  enable_thin_provisioning = ${state.vdc.enable_thin_provisioning}`);
    lines.push(`  enable_fast_provisioning = ${state.vdc.enable_fast_provisioning}`);
    lines.push(`  delete_force             = ${state.vdc.delete_force}`);
    lines.push(`  delete_recursive         = ${state.vdc.delete_recursive}`);
    if (state.vdc.description) {
      lines.push(`  description              = "${state.vdc.description}"`);
    }
    lines.push(``);
    lines.push(`  depends_on = [time_sleep.wait_for_org]`);
    lines.push(`}`);
  }

  // --- Edge Gateway (NSX-T) ---
  if (state.edge.name && state.edge.external_network_name && state.edge.subnet.gateway) {
    const extSlug = slug(state.edge.external_network_name);
    const vdcSlug = slug(state.vdc.name);

    lines.push(``);
    lines.push(`data "vcd_external_network_v2" "${extSlug}" {`);
    lines.push(`  name = "${state.edge.external_network_name}"`);
    lines.push(`}`);
    lines.push(``);
    lines.push(`data "vcd_org_vdc" "${vdcSlug}_for_edge" {`);
    lines.push(`  org  = "${state.org.name}"`);
    lines.push(`  name = "${state.vdc.name}"`);
    lines.push(`}`);
    lines.push(``);
    lines.push(`resource "vcd_nsxt_edgegateway" "${slug(state.edge.name)}" {`);
    lines.push(`  org                       = "${state.org.name}"`);
    lines.push(`  name                      = "${state.edge.name}"`);
    lines.push(`  owner_id                  = data.vcd_org_vdc.${vdcSlug}_for_edge.id`);
    lines.push(`  external_network_id       = data.vcd_external_network_v2.${extSlug}.id`);
    lines.push(`  dedicate_external_network = ${state.edge.dedicate_external_network}`);
    if (state.edge.description) {
      lines.push(`  description               = "${state.edge.description}"`);
    }
    lines.push(``);
    lines.push(`  subnet {`);
    lines.push(`    gateway       = "${state.edge.subnet.gateway}"`);
    lines.push(`    prefix_length = ${state.edge.subnet.prefix_length}`);
    lines.push(`    primary_ip    = "${state.edge.subnet.primary_ip}"`);
    if (state.edge.subnet.start_address && state.edge.subnet.end_address) {
      lines.push(``);
      lines.push(`    allocated_ips {`);
      lines.push(`      start_address = "${state.edge.subnet.start_address}"`);
      lines.push(`      end_address   = "${state.edge.subnet.end_address}"`);
      lines.push(`    }`);
    }
    lines.push(`  }`);
    lines.push(`}`);
  }

  // --- Routed Network ---
  if (state.network.name && state.network.gateway && state.edge.name) {
    const edgeSlug = slug(state.edge.name);

    lines.push(``);
    lines.push(`data "vcd_nsxt_edgegateway" "${edgeSlug}_for_network" {`);
    lines.push(`  org  = "${state.org.name}"`);
    lines.push(`  vdc  = "${state.vdc.name}"`);
    lines.push(`  name = "${state.edge.name}"`);
    lines.push(`}`);
    lines.push(``);
    lines.push(`resource "vcd_network_routed_v2" "${slug(state.network.name)}" {`);
    lines.push(`  org             = "${state.org.name}"`);
    lines.push(`  name            = "${state.network.name}"`);
    lines.push(`  edge_gateway_id = data.vcd_nsxt_edgegateway.${edgeSlug}_for_network.id`);
    lines.push(`  gateway         = "${state.network.gateway}"`);
    lines.push(`  prefix_length   = ${state.network.prefix_length}`);
    if (state.network.dns1) {
      lines.push(`  dns1            = "${state.network.dns1}"`);
    }
    if (state.network.dns2) {
      lines.push(`  dns2            = "${state.network.dns2}"`);
    }
    if (state.network.description) {
      lines.push(`  description     = "${state.network.description}"`);
    }
    if (state.network.static_ip_pool) {
      lines.push(``);
      lines.push(`  static_ip_pool {`);
      lines.push(`    start_address = "${state.network.static_ip_pool.start_address}"`);
      lines.push(`    end_address   = "${state.network.static_ip_pool.end_address}"`);
      lines.push(`  }`);
    }
    lines.push(`}`);
  }

  // --- vApp ---
  if (state.vapp.name && state.vdc.name) {
    const vdcSlug = slug(state.vdc.name);

    lines.push(``);
    lines.push(`data "vcd_org_vdc" "${vdcSlug}_for_vapp" {`);
    lines.push(`  org  = "${state.org.name}"`);
    lines.push(`  name = "${state.vdc.name}"`);
    lines.push(`}`);
    lines.push(``);
    lines.push(`resource "vcd_vapp" "${slug(state.vapp.name)}" {`);
    lines.push(`  org      = "${state.org.name}"`);
    lines.push(`  vdc      = data.vcd_org_vdc.${vdcSlug}_for_vapp.name`);
    lines.push(`  name     = "${state.vapp.name}"`);
    lines.push(`  power_on = ${state.vapp.power_on}`);
    if (state.vapp.description) {
      lines.push(`  description = "${state.vapp.description}"`);
    }
    lines.push(`}`);
  }

  // --- vApp VM ---
  if (state.vm.name && state.vm.catalog_name && state.vm.template_name && state.vapp.name) {
    const catSlug = slug(state.vm.catalog_name);
    const tplSlug = slug(state.vm.template_name);

    lines.push(``);
    lines.push(`data "vcd_catalog" "${catSlug}" {`);
    lines.push(`  org  = "${state.org.name}"`);
    lines.push(`  name = "${state.vm.catalog_name}"`);
    lines.push(`}`);
    lines.push(``);
    lines.push(`data "vcd_catalog_vapp_template" "${tplSlug}" {`);
    lines.push(`  org        = "${state.org.name}"`);
    lines.push(`  catalog_id = data.vcd_catalog.${catSlug}.id`);
    lines.push(`  name       = "${state.vm.template_name}"`);
    lines.push(`}`);
    lines.push(``);
    lines.push(`resource "vcd_vapp_vm" "${slug(state.vm.name)}" {`);
    lines.push(`  org              = "${state.org.name}"`);
    lines.push(`  vdc              = "${state.vdc.name}"`);
    lines.push(`  vapp_name        = "${state.vapp.name}"`);
    lines.push(`  name             = "${state.vm.name}"`);
    lines.push(`  computer_name    = "${state.vm.computer_name}"`);
    lines.push(`  vapp_template_id = data.vcd_catalog_vapp_template.${tplSlug}.id`);
    lines.push(`  memory           = ${state.vm.memory}`);
    lines.push(`  cpus             = ${state.vm.cpus}`);
    lines.push(`  cpu_cores        = ${state.vm.cpu_cores}`);
    lines.push(`  power_on         = ${state.vm.power_on}`);
    if (state.vm.storage_profile) {
      lines.push(`  storage_profile  = "${state.vm.storage_profile}"`);
    }
    if (state.vm.description) {
      lines.push(`  description      = "${state.vm.description}"`);
    }
    if (state.vm.network?.name) {
      lines.push(``);
      lines.push(`  network {`);
      lines.push(`    type               = "${state.vm.network.type}"`);
      lines.push(`    name               = "${state.vm.network.name}"`);
      lines.push(`    ip_allocation_mode = "${state.vm.network.ip_allocation_mode}"`);
      if (state.vm.network.ip) {
        lines.push(`    ip                 = "${state.vm.network.ip}"`);
      }
      lines.push(`  }`);
    }
    lines.push(`}`);
  }

  return lines.join("\n");
}

/* ------------------------------------------------------------------ */
/*  Syntax colouring (lightweight, no external lib)                   */
/* ------------------------------------------------------------------ */

function tokenizeLine(line: string): React.ReactNode {
  // HCL keyword at start of line
  if (/^\s*(resource|provider|variable|terraform|backend|data|output|locals|module)\b/.test(line)) {
    return colourKeywordLine(line);
  }
  // Attribute = value
  if (/^\s*\w[\w-]*\s*=/.test(line)) {
    return colourAssignment(line);
  }
  // Comments
  if (/^\s*(#|\/\/)/.test(line)) {
    return <span className="text-slate-600">{line}</span>;
  }
  // Block braces or blank
  return <span className="text-slate-400">{line}</span>;
}

function colourKeywordLine(line: string): React.ReactNode {
  const match = line.match(/^(\s*)(resource|provider|variable|terraform|backend|data|output|locals|module)(.*)$/);
  if (!match) return line;
  const [, indent, keyword, rest = ""] = match;
  return (
    <>
      {indent}
      <span className="text-purple-400 font-semibold">{keyword}</span>
      <span className="text-blue-300">{colourStrings(rest)}</span>
    </>
  );
}

function colourAssignment(line: string): React.ReactNode {
  const eqIndex = line.indexOf("=");
  if (eqIndex === -1) return line;
  const attr = line.slice(0, eqIndex);
  const val = line.slice(eqIndex);
  return (
    <>
      <span className="text-sky-300">{attr}</span>
      <span className="text-slate-500">=</span>
      <span className="text-amber-300">{colourStrings(val.slice(1))}</span>
    </>
  );
}

function colourStrings(text: string): React.ReactNode {
  const parts = text.split(/(".*?")/g);
  return parts.map((part, i) =>
    part.startsWith('"') ? (
      <span key={i} className="text-emerald-400">{part}</span>
    ) : /true|false/.test(part) ? (
      <span key={i} className="text-orange-400">{part}</span>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function HclPreview() {
  const state = useConfigStore();
  const [copied, setCopied] = useState(false);

  const hcl = useMemo(
    () => generateHcl(state),
    [state.provider, state.backend, state.org, state.vdc, state.edge, state.network, state.vapp, state.vm]
  );

  const handleCopy = async () => {
    await navigator.clipboard.writeText(hcl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([hcl], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "main.tf";
    a.click();
    URL.revokeObjectURL(url);
  };

  const lines = hcl.split("\n");

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-clr-light-gray border-b border-clr-border">
        <div className="flex items-center gap-2">
          <span className="text-clr-text font-semibold tracking-tight text-sm">
            main.tf
          </span>
          <span className="text-[10px] text-clr-text-secondary">
            {lines.length} lines
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs text-clr-text-secondary hover:text-clr-text bg-white border border-clr-border rounded-sm px-2.5 py-1 transition-colors"
          >
            {copied ? (
              <Check className="h-3 w-3 text-emerald-400" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 text-xs text-clr-text-secondary hover:text-clr-text bg-white border border-clr-border rounded-sm px-2.5 py-1 transition-colors"
          >
            <Download className="h-3 w-3" />
            .tf
          </button>
        </div>
      </div>

      {/* Code view */}
      <div className="flex-1 overflow-auto bg-[#0d1117] p-4">
        <pre className="font-mono text-sm leading-6">
          {lines.map((line, i) => (
            <div key={i} className="flex">
              <span className="select-none w-10 flex-none text-right pr-4 text-slate-600 text-xs leading-6">
                {i + 1}
              </span>
              <code>{tokenizeLine(line)}</code>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
