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
  vdc: { name: string; provider_vdc_name: string; allocation_model: string; description: string };
}): string {
  const lines: string[] = [];

  // --- Provider / Backend ---
  lines.push(`terraform {`);
  lines.push(`  required_providers {`);
  lines.push(`    vcd = {`);
  lines.push(`      source  = "vmware/vcd"`);
  lines.push(`      version = "~> 3.12"`);
  lines.push(`    }`);
  lines.push(`  }`);
  lines.push(``);
  lines.push(`  backend "s3" {`);
  lines.push(`    bucket                      = "${state.backend.bucket}"`);
  lines.push(`    key                         = "${slug(state.org.name || "default")}/terraform.tfstate"`);
  lines.push(`    region                      = "${state.backend.region}"`);
  lines.push(`    endpoint                    = "${state.backend.endpoint}"`);
  lines.push(`    skip_credentials_validation = true`);
  lines.push(`    skip_metadata_api_check     = true`);
  lines.push(`    force_path_style            = true`);
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
  }

  // --- VDC ---
  if (state.vdc.name && state.vdc.provider_vdc_name) {
    lines.push(``);
    lines.push(`resource "vcd_org_vdc" "${slug(state.vdc.name)}" {`);
    lines.push(`  name              = "${state.vdc.name}"`);
    lines.push(`  org               = "${state.org.name}"`);
    lines.push(`  provider_vdc_name = "${state.vdc.provider_vdc_name}"`);
    lines.push(`  allocation_model  = "${state.vdc.allocation_model}"`);
    if (state.vdc.description) {
      lines.push(`  description       = "${state.vdc.description}"`);
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
  const [, indent, keyword, rest] = match;
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
    [state.provider, state.backend, state.org, state.vdc]
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
      <div className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <span className="text-white font-semibold tracking-tight text-sm">
            main.tf
          </span>
          <span className="text-[10px] text-slate-500">
            {lines.length} lines
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 bg-slate-800/60 border border-slate-700/50 rounded-md px-2.5 py-1 transition-colors"
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
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 bg-slate-800/60 border border-slate-700/50 rounded-md px-2.5 py-1 transition-colors"
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
