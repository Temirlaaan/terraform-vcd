import { Shield, ArrowRightLeft, Network, Route } from "lucide-react";
import type { MigrationSummary as MigrationSummaryType } from "@/api/migrationApi";

interface MigrationSummaryProps {
  summary: MigrationSummaryType;
  edgeName: string;
}

function StatCard({
  icon: Icon,
  title,
  items,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  items: { label: string; value: number }[];
}) {
  return (
    <div className="bg-white border border-clr-border rounded-sm p-3">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="h-3.5 w-3.5 text-clr-action" />
        <span className="text-xs font-semibold text-clr-text">{title}</span>
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <div key={item.label} className="flex items-center justify-between">
            <span className="text-[11px] text-clr-text-secondary">{item.label}</span>
            <span className="text-xs font-medium text-clr-text tabular-nums">
              {item.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MigrationSummary({ summary, edgeName }: MigrationSummaryProps) {
  return (
    <div className="px-4 py-3">
      <h3 className="text-xs font-semibold text-clr-text mb-2">
        Migration Summary — {edgeName}
      </h3>
      <div className="grid grid-cols-2 gap-2">
        <StatCard
          icon={Shield}
          title="Firewall Rules"
          items={[
            { label: "Total", value: summary.firewall_rules_total },
            { label: "User", value: summary.firewall_rules_user },
            { label: "System", value: summary.firewall_rules_system },
          ]}
        />
        <StatCard
          icon={ArrowRightLeft}
          title="NAT Rules"
          items={[{ label: "Total", value: summary.nat_rules_total }]}
        />
        <StatCard
          icon={Network}
          title="App Port Profiles"
          items={[
            { label: "Total", value: summary.app_port_profiles_total },
            { label: "System", value: summary.app_port_profiles_system },
            { label: "Custom", value: summary.app_port_profiles_custom },
          ]}
        />
        <StatCard
          icon={Route}
          title="Static Routes"
          items={[{ label: "Total", value: summary.static_routes_total }]}
        />
      </div>
    </div>
  );
}
