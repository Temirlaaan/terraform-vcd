import { ShieldCheck, ShieldOff, KeyRound, AlertTriangle } from "lucide-react";
import { cn } from "@/utils/cn";
import type { IpsecTunnel } from "@/api/ipsecMigrationApi";

/* What will and will not move, and why.

   A tunnel that cannot be migrated is shown rather than hidden: leaving
   it off the list would read as "this edge had fewer tunnels". */

function Crypto({ t }: { t: IpsecTunnel }) {
  if (!t.migratable) return <span className="text-clr-placeholder">—</span>;
  return (
    <span className="font-mono text-[11px] text-clr-text-secondary">
      {[t.ike_version, t.encryption, t.digest, t.dh_group]
        .filter(Boolean)
        .join(" · ")}
      {t.pfs && " · PFS"}
    </span>
  );
}

export function IpsecTunnelTable({ tunnels }: { tunnels: IpsecTunnel[] }) {
  if (tunnels.length === 0) return null;

  return (
    <section className="rounded-card border border-clr-border-subtle bg-clr-surface shadow-card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left border-b border-clr-border-subtle bg-clr-surface-sunken">
            {["Tunnel", "Endpoints", "Networks", "Crypto", ""].map((h, i) => (
              <th
                key={i}
                className="px-4 py-2 text-xs font-medium text-clr-text-secondary"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tunnels.map((t, i) => (
            <tr
              key={`${t.name}-${i}`}
              className={cn(
                "border-b border-clr-border-subtle last:border-0 align-top",
                !t.migratable && "bg-clr-warning-bg/60",
              )}
            >
              <td className="px-4 py-2.5">
                <div className="flex items-center gap-1.5">
                  {t.migratable ? (
                    <ShieldCheck className="h-3.5 w-3.5 text-clr-success shrink-0" />
                  ) : (
                    <ShieldOff className="h-3.5 w-3.5 text-clr-warning shrink-0" />
                  )}
                  <span className="font-medium text-clr-text">{t.name}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[11px] text-clr-text-secondary">
                  <span>
                    {t.enabled_on_source ? "enabled" : "disabled"} on source
                  </span>
                  {t.migratable && (
                    <span
                      className={cn(
                        "inline-flex items-center gap-0.5",
                        t.psk_readable ? "text-clr-success-text" : "text-clr-danger",
                      )}
                      title={
                        t.psk_readable
                          ? "Key read from the source; it is not sent to this page"
                          : "No key returned — terraform cannot plan this tunnel"
                      }
                    >
                      <KeyRound className="h-3 w-3" />
                      {t.psk_readable ? "key ok" : "no key"}
                    </span>
                  )}
                </div>
              </td>

              <td className="px-4 py-2.5 font-mono text-[11px] text-clr-text-secondary">
                <div>{t.local_ip}</div>
                <div>→ {t.peer_ip}</div>
                {t.remote_id && (
                  <div
                    className="text-clr-warning-text"
                    title="The peer is behind NAT and announces this identity. Written explicitly, or phase 1 fails as an auth error."
                  >
                    id: {t.remote_id}
                  </div>
                )}
              </td>

              <td className="px-4 py-2.5 font-mono text-[11px] text-clr-text-secondary">
                <div>{t.local_networks.join(", ") || "—"}</div>
                <div>→ {t.remote_networks.join(", ") || "—"}</div>
              </td>

              <td className="px-4 py-2.5">
                <Crypto t={t} />
              </td>

              <td className="px-4 py-2.5">
                {!t.migratable && (
                  <div className="text-[11px] text-clr-warning-text max-w-xs">
                    <div className="flex items-center gap-1 font-medium">
                      <AlertTriangle className="h-3 w-3" />
                      Stays on the source
                    </div>
                    {t.unsupported.map((u, j) => (
                      <div key={j} className="mt-0.5">
                        {u}
                      </div>
                    ))}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
