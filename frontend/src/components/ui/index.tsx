import { Loader2 } from "lucide-react";
import type { ReactNode, ButtonHTMLAttributes } from "react";
import { cn } from "@/utils/cn";

/* Shared building blocks.

   Every page used to declare its own button and card classes inline,
   which is how a design drifts: two buttons that should look identical
   end up a pixel and a shade apart. These are the only places those
   decisions live now. */

/* ------------------------------------------------------------------ */
/*  Button                                                             */
/* ------------------------------------------------------------------ */

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  icon?: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-clr-action text-white border border-clr-action hover:bg-clr-action-hover hover:border-clr-action-hover",
  secondary:
    "bg-clr-surface text-clr-text border border-clr-border hover:border-clr-placeholder hover:bg-clr-surface-sunken",
  ghost:
    "bg-transparent text-clr-text-secondary border border-transparent hover:bg-clr-surface-sunken hover:text-clr-text",
  danger:
    "bg-clr-danger text-white border border-clr-danger hover:brightness-110",
};

export function Button({
  variant = "secondary",
  loading = false,
  icon,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center gap-2 rounded px-3 py-1.5 text-sm font-medium",
        "transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-clr-action-light",
        "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-inherit",
        VARIANTS[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Card                                                               */
/* ------------------------------------------------------------------ */

interface CardProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** Drop the inner padding when the card holds a full-bleed table. */
  flush?: boolean;
  className?: string;
  children?: ReactNode;
}

export function Card({
  title,
  description,
  actions,
  flush = false,
  className,
  children,
}: CardProps) {
  return (
    <section
      className={cn(
        "rounded-card border border-clr-border-subtle bg-clr-surface shadow-card",
        className,
      )}
    >
      {(title || actions) && (
        <header
          className={cn(
            "flex items-start justify-between gap-4 px-4 pt-4",
            !description && "pb-1",
          )}
        >
          <div className="min-w-0">
            {title && <h2 className="text-section-title text-clr-text">{title}</h2>}
            {description && (
              <p className="mt-0.5 text-xs text-clr-text-secondary">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="flex-none">{actions}</div>}
        </header>
      )}
      <div className={cn(!flush && "p-4", title && !flush && "pt-3")}>
        {children}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  PageHeader                                                         */
/* ------------------------------------------------------------------ */

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <h1 className="text-page-title text-clr-text">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-clr-text-secondary max-w-2xl">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex-none pt-1">{actions}</div>}
    </header>
  );
}

/* ------------------------------------------------------------------ */
/*  Callout                                                            */
/* ------------------------------------------------------------------ */

type Tone = "info" | "success" | "warning" | "danger";

const TONES: Record<Tone, string> = {
  info: "bg-clr-info-bg text-clr-info-text",
  success: "bg-clr-success-bg text-clr-success-text",
  warning: "bg-clr-warning-bg text-clr-warning-text",
  danger: "bg-clr-danger-bg text-clr-danger-text",
};

export function Callout({
  tone = "info",
  title,
  icon,
  children,
  className,
}: {
  tone?: Tone;
  title?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn("rounded-card px-4 py-3 text-xs", TONES[tone], className)}
    >
      {title && (
        <h3 className="flex items-center gap-1.5 font-semibold mb-1">
          {icon}
          {title}
        </h3>
      )}
      <div className="space-y-0.5">{children}</div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Badge                                                              */
/* ------------------------------------------------------------------ */

export function Badge({
  tone = "info",
  children,
  className,
}: {
  tone?: Tone | "neutral";
  children: ReactNode;
  className?: string;
}) {
  const tones = {
    ...TONES,
    neutral: "bg-clr-surface-sunken text-clr-text-secondary",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Stat row                                                           */
/* ------------------------------------------------------------------ */

export function Stats({
  items,
}: {
  items: { label: string; value: ReactNode; tone?: Tone }[];
}) {
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-2">
      {items.map((s) => (
        <div key={s.label}>
          <dt className="text-xs text-clr-text-secondary">{s.label}</dt>
          <dd
            className={cn(
              "text-xl font-semibold tabular-nums",
              s.tone === "warning" && "text-clr-warning",
              s.tone === "danger" && "text-clr-danger",
              s.tone === "success" && "text-clr-success",
              !s.tone && "text-clr-text",
            )}
          >
            {s.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
