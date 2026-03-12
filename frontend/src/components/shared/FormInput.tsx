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
      <span className="text-xs font-medium text-slate-400">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full rounded-md bg-slate-800/70 border border-slate-700/50 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 disabled:opacity-50 disabled:cursor-not-allowed focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 focus:outline-none transition-colors"
      />
    </label>
  );
}
