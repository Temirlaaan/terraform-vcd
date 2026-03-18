interface FormInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

export function FormInput({
  label,
  value,
  onChange,
  placeholder,
  disabled,
}: FormInputProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-clr-text-secondary">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text placeholder:text-clr-placeholder disabled:opacity-50 disabled:cursor-not-allowed focus:border-clr-action focus:outline-none transition-colors"
      />
    </label>
  );
}
