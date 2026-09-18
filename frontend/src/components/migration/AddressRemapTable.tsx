import { ArrowRight } from "lucide-react";
import { cn } from "@/utils/cn";
import type { AddressUse } from "@/api/cloudMigrationApi";

/* Rewrite source addresses for the destination cloud.

   The destination allocates its own public IPs, so every NAT rule and IP
   set naming the source address has to be rewritten. Addresses are listed
   with where they came from, external ones first, because those are the
   ones that always need changing. */

const KIND_LABEL: Record<AddressUse["kind"], string> = {
  external: "Public (NAT)",
  ip_set: "IP set",
  internal: "Internal",
  route: "Static route",
};

const KIND_STYLE: Record<AddressUse["kind"], string> = {
  external: "bg-amber-100 text-amber-900",
  ip_set: "bg-sky-100 text-sky-900",
  internal: "bg-slate-100 text-slate-700",
  route: "bg-slate-100 text-slate-700",
};

const IPV4 =
  /^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;

export function isValidIpv4(v: string): boolean {
  return IPV4.test(v.trim());
}

interface AddressRemapTableProps {
  addresses: AddressUse[];
  mapping: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}

export function AddressRemapTable({
  addresses,
  mapping,
  onChange,
}: AddressRemapTableProps) {
  if (addresses.length === 0) return null;

  const setValue = (address: string, raw: string) => {
    const next = { ...mapping };
    const value = raw.trim();
    if (value) next[address] = value;
    else delete next[address];
    onChange(next);
  };

  const unmappedExternal = addresses.filter(
    (a) => a.kind === "external" && !mapping[a.address],
  ).length;

  return (
    <section className="rounded-sm border border-clr-border bg-white p-4">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-clr-text">
          Address remapping
        </h2>
        <p className="text-xs text-clr-text-secondary mt-0.5">
          Leave a field empty to keep the address as it is. Public addresses
          almost always need changing — the destination cloud does not own the
          source's.
        </p>
      </header>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left">
            <th className="pb-1.5 text-xs font-medium text-clr-text-secondary">
              Source address
            </th>
            <th className="pb-1.5 w-8" />
            <th className="pb-1.5 text-xs font-medium text-clr-text-secondary">
              Address on destination
            </th>
            <th className="pb-1.5 text-xs font-medium text-clr-text-secondary">
              Used by
            </th>
          </tr>
        </thead>
        <tbody>
          {addresses.map((a) => {
            const value = mapping[a.address] ?? "";
            const invalid = value !== "" && !isValidIpv4(value);
            return (
              <tr key={a.address} className="border-t border-clr-border">
                <td className="py-1.5 pr-3 align-top">
                  <div className="flex items-center gap-2">
                    <code className="font-mono text-xs text-clr-text">
                      {a.address}
                    </code>
                    <span
                      className={cn(
                        "rounded-sm px-1.5 py-0.5 text-[10px] font-medium",
                        KIND_STYLE[a.kind],
                      )}
                    >
                      {KIND_LABEL[a.kind]}
                    </span>
                  </div>
                </td>
                <td className="py-1.5 align-top">
                  <ArrowRight className="h-3.5 w-3.5 text-clr-placeholder" />
                </td>
                <td className="py-1.5 pr-3 align-top">
                  <input
                    value={value}
                    onChange={(e) => setValue(a.address, e.target.value)}
                    placeholder="unchanged"
                    spellCheck={false}
                    className={cn(
                      "w-44 rounded-sm border bg-white px-2 py-1 font-mono text-xs",
                      "focus:outline-none focus:border-clr-action",
                      invalid ? "border-clr-danger" : "border-clr-border",
                    )}
                  />
                  {invalid && (
                    <p className="text-[11px] text-clr-danger mt-0.5">
                      Not a valid IPv4 address
                    </p>
                  )}
                </td>
                <td className="py-1.5 align-top text-xs text-clr-text-secondary">
                  {a.used_by.slice(0, 2).join(", ") || "—"}
                  {a.occurrences > 1 && (
                    <span className="text-clr-placeholder">
                      {" "}
                      ({a.occurrences}×)
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {unmappedExternal > 0 && (
        <p className="mt-3 text-xs text-amber-800">
          {unmappedExternal} public address
          {unmappedExternal > 1 ? "es are" : " is"} still pointing at the source
          cloud.
        </p>
      )}
    </section>
  );
}
