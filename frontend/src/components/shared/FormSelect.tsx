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
      <span className="text-xs font-medium text-clr-text-secondary">{label}</span>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled || isLoading}
          className={cn(
            "w-full appearance-none rounded-sm bg-white border px-2.5 py-1.5 pr-8 text-sm text-clr-text",
            "focus:border-clr-action focus:outline-none transition-colors",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            error
              ? "border-clr-danger"
              : "border-clr-border"
          )}
        >
          <option value="" className="bg-white text-clr-placeholder">
            {isLoading ? "Loading..." : placeholder}
          </option>
          {options.map((opt) => (
            <option
              key={opt.value}
              value={opt.value}
              className="bg-white text-clr-text"
            >
              {opt.label}
            </option>
          ))}
        </select>

        {/* Right icon: spinner or chevron */}
        <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5">
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 text-clr-placeholder animate-spin" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-clr-placeholder" />
          )}
        </div>
      </div>

      {error && (
        <p className="text-[11px] text-clr-danger">{error}</p>
      )}
    </label>
  );
}
