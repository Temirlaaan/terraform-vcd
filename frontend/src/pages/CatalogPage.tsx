import { Link } from "react-router-dom";
import { Building2, HardDrive, Network, Wifi, Server, ArrowLeftRight, ArrowRight } from "lucide-react";
import { cn } from "@/utils/cn";

interface CatalogCard {
  title: string;
  description: string;
  icons: React.ComponentType<{ className?: string }>[];
  badge: string;
  to?: string;
  disabled?: boolean;
}

const cards: CatalogCard[] = [
  {
    title: "Basic Tenant (Org + VDC)",
    description:
      "Create an Organization with a Virtual Data Center, including compute, memory, and storage allocation.",
    icons: [Building2, HardDrive],
    badge: "Foundation",
    to: "/provision",
  },
  {
    title: "Edge Gateway + Network",
    description:
      "Provision an NSX-T Edge Gateway with a routed network, NAT rules, and firewall policies.",
    icons: [Network, Wifi],
    badge: "Networking",
    disabled: true,
  },
  {
    title: "Edge Migration (NSX-V → NSX-T)",
    description:
      "Migrate firewall rules, NAT rules, and static routes from a legacy NSX-V edge gateway to NSX-T.",
    icons: [ArrowLeftRight],
    badge: "Migration",
    to: "/migration",
  },
  {
    title: "Full Stack (Org → VM)",
    description:
      "End-to-end provisioning: Organization, VDC, Edge Gateway, Network, vApp, and Virtual Machine.",
    icons: [Server],
    badge: "Complete",
    disabled: true,
  },
];

function Card({ card }: { card: CatalogCard }) {
  const content = (
    <div
      className={cn(
        "bg-white border border-clr-border rounded-sm p-5 flex flex-col gap-4 transition-all",
        card.disabled
          ? "opacity-50 cursor-not-allowed"
          : "hover:shadow-md hover:border-clr-action/40"
      )}
    >
      {/* Icons row */}
      <div className="flex items-center gap-2">
        {card.icons.map((Icon, i) => (
          <div
            key={i}
            className="h-9 w-9 rounded-sm bg-clr-action/10 flex items-center justify-center"
          >
            <Icon className="h-4.5 w-4.5 text-clr-action" />
          </div>
        ))}
      </div>

      {/* Title + badge */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-clr-text leading-tight">
          {card.title}
        </h3>
        <span className="flex-none text-[10px] font-medium text-clr-action bg-clr-action/10 border border-clr-action/20 rounded px-1.5 py-0.5">
          {card.badge}
        </span>
      </div>

      {/* Description */}
      <p className="text-xs text-clr-text-secondary leading-relaxed">
        {card.description}
      </p>

      {/* Action */}
      <div className="mt-auto pt-1">
        {card.disabled ? (
          <span className="text-xs text-clr-placeholder italic">
            Coming soon
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-clr-action">
            Provision
            <ArrowRight className="h-3.5 w-3.5" />
          </span>
        )}
      </div>
    </div>
  );

  if (card.disabled || !card.to) {
    return content;
  }

  return <Link to={card.to}>{content}</Link>;
}

export function CatalogPage() {
  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-clr-text tracking-tight">
          Service Catalog
        </h1>
        <p className="text-xs text-clr-text-secondary mt-1">
          Select a template to provision VCD infrastructure via Terraform.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {cards.map((card) => (
          <Card key={card.title} card={card} />
        ))}
      </div>
    </div>
  );
}
