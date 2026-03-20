import { Network, Wifi, Box, Monitor } from "lucide-react";
import { RotateCcw } from "lucide-react";
import { useConfigStore } from "@/store/useConfigStore";
import { OrgSection, VdcSection, ActionBar, Section } from "@/components/provision";
import { HclPreview } from "@/components/HclPreview";

export function ProvisionPage() {
  const resetAll = useConfigStore((s) => s.resetAll);

  return (
    <div className="flex flex-1 min-h-0">
      {/* Left panel — config form */}
      <aside className="w-96 flex-none bg-clr-near-white border-r border-clr-border overflow-y-auto flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h2 className="text-clr-text font-semibold tracking-tight text-sm">
            Basic Tenant
          </h2>
          <button
            onClick={resetAll}
            className="text-clr-placeholder hover:text-clr-text transition-colors"
            title="Reset all fields"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Accordion sections */}
        <div className="flex-1 overflow-y-auto">
          <OrgSection />
          <VdcSection />
          <Section title="Edge Gateway" icon={Network} disabled />
          <Section title="Routed Network" icon={Wifi} disabled />
          <Section title="vApp" icon={Box} disabled />
          <Section title="Virtual Machine" icon={Monitor} disabled />
        </div>

        {/* Plan / Apply buttons */}
        <ActionBar />
      </aside>

      {/* Right panel — HCL preview */}
      <div className="flex-1 min-w-0 overflow-hidden">
        <HclPreview />
      </div>
    </div>
  );
}
