interface FormNumberInputProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
  placeholder?: string;
  disabled?: boolean;
  min?: number;
  step?: number;
}

export function FormNumberInput({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  min,
  step,
}: FormNumberInputProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-clr-text-secondary">{label}</span>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        placeholder={placeholder}
        disabled={disabled}
        min={min}
        step={step}
        className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text placeholder:text-clr-placeholder disabled:opacity-50 disabled:cursor-not-allowed focus:border-clr-action focus:outline-none transition-colors"
      />
    </label>
  );
}
