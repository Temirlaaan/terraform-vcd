interface FormCheckboxProps {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}

export function FormCheckbox({
  label,
  checked,
  onChange,
  disabled,
}: FormCheckboxProps) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="h-3.5 w-3.5 rounded border-clr-border bg-white text-clr-action focus:ring-2 focus:ring-clr-action/30 focus:ring-offset-0 disabled:opacity-50 disabled:cursor-not-allowed"
      />
      <span className="text-xs font-medium text-clr-text-secondary">{label}</span>
    </label>
  );
}
