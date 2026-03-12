import { ChevronDown, Loader2 } from "lucide-react";
import { cn } from "@/utils/cn";

export interface SelectOption {
  label: string;
  value: string;
}

interface FormSelectProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  isLoading?: boolean;
  disabled?: boolean;
  error?: string;
}

export function FormSelect({
  label,
  value,
  onChange,
  options,
  placeholder = "Select...",
  isLoading = false,
  disabled = false,
  error,
}: FormSelectProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-slate-400">{label}</span>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled || isLoading}
          className={cn(
            "w-full appearance-none rounded-md bg-slate-800/70 border px-3 py-1.5 pr-8 text-sm text-slate-200",
            "focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 focus:outline-none transition-colors",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            error
              ? "border-rose-500/50"
              : "border-slate-700/50"
          )}
        >
          <option value="" className="bg-slate-900 text-slate-500">
            {isLoading ? "Loading..." : placeholder}
          </option>
          {options.map((opt) => (
            <option
              key={opt.value}
              value={opt.value}
              className="bg-slate-900 text-slate-200"
            >
              {opt.label}
            </option>
          ))}
        </select>

        {/* Right icon: spinner or chevron */}
        <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5">
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 text-slate-500 animate-spin" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-slate-500" />
          )}
        </div>
      </div>

      {error && (
        <p className="text-[11px] text-rose-400">{error}</p>
      )}
    </label>
  );
}
