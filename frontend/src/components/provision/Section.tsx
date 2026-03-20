import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/utils/cn";

export function Section({
  title,
  icon: Icon,
  badge,
  defaultOpen = false,
  disabled = false,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  defaultOpen?: boolean;
  disabled?: boolean;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  if (disabled) {
    return (
      <div className="border-b border-clr-border opacity-50">
        <div className="flex w-full items-center gap-2.5 px-4 py-3 text-xs font-semibold tracking-wide uppercase text-clr-placeholder cursor-not-allowed">
          <ChevronRight className="h-3.5 w-3.5" />
          <Icon className="h-4 w-4" />
          {title}
          <span className="ml-auto text-[10px] font-normal italic text-clr-placeholder">
            Coming soon
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-clr-border">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-xs font-semibold tracking-wide uppercase text-clr-text-secondary hover:text-clr-text transition-colors"
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            open && "rotate-90"
          )}
        />
        <Icon className="h-4 w-4" />
        {title}
        {badge && (
          <span className="ml-auto text-[10px] font-medium text-clr-action bg-[#0079b8]/10 border border-[#0079b8]/20 rounded px-1.5 py-0.5">
            {badge}
          </span>
        )}
      </button>
      {open && <div className="px-4 pb-4 space-y-3">{children}</div>}
    </div>
  );
}
