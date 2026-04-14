import { Copy, Check, Download } from "lucide-react";
import { useState } from "react";
import { tokenizeLine } from "@/components/HclPreview";

interface MigrationHclPreviewProps {
  hcl: string;
  edgeName: string;
}

export function MigrationHclPreview({ hcl, edgeName }: MigrationHclPreviewProps) {
  const [copied, setCopied] = useState(false);

  const lines = hcl.split("\n");

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
    a.download = `migration_${edgeName.toLowerCase().replace(/[^a-z0-9]+/g, "_")}.tf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-clr-light-gray border-b border-clr-border">
        <div className="flex items-center gap-2">
          <span className="text-clr-text font-semibold tracking-tight text-sm">
            migration_{edgeName.toLowerCase().replace(/[^a-z0-9]+/g, "_")}.tf
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
