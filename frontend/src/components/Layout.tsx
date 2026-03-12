import {
  Cloud,
  ChevronDown,
  Terminal as TerminalIcon,
  LogOut,
} from "lucide-react";
import { cn } from "@/utils/cn";
import { useConfigStore } from "@/store/useConfigStore";
import { useAuth } from "@/auth/useAuth";
import { Sidebar } from "./Sidebar";
import { HclPreview } from "./HclPreview";
import { TerminalDrawer } from "./TerminalDrawer";

/* ------------------------------------------------------------------ */
/*  TopBar                                                            */
/* ------------------------------------------------------------------ */

function TopBar() {
  const toggleTerminal = useConfigStore((s) => s.toggleTerminal);
  const terminalOpen = useConfigStore((s) => s.terminalOpen);
  const { fullName, username, logout } = useAuth();

  const displayName = fullName || username || "User";
  const initials = displayName
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <header className="h-14 flex-none flex items-center justify-between gap-4 bg-slate-900 border-b border-slate-800 px-4">
      {/* Left — branding */}
      <div className="flex items-center gap-3">
        <Cloud className="h-5 w-5 text-blue-500" />
        <span className="text-white font-semibold tracking-tight text-sm">
          Terraform VCD Dashboard
        </span>
        <span className="text-[10px] font-medium text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">
          v0.1
        </span>
      </div>

      {/* Center — environment switcher */}
      <button className="flex items-center gap-1.5 text-xs text-slate-400 bg-slate-800/60 border border-slate-700/50 rounded-md px-3 py-1.5 hover:border-slate-600 transition-colors">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        vcd-prod-01
        <ChevronDown className="h-3 w-3 text-slate-500" />
      </button>

      {/* Right — actions & user */}
      <div className="flex items-center gap-2">
        <button
          onClick={toggleTerminal}
          className={cn(
            "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border transition-colors",
            terminalOpen
              ? "bg-blue-600/20 border-blue-500/30 text-blue-400"
              : "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-slate-600"
          )}
        >
          <TerminalIcon className="h-3.5 w-3.5" />
          Terminal
        </button>

        {/* User avatar + name */}
        <div className="flex items-center gap-2 ml-1">
          <div className="h-8 w-8 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center">
            <span className="text-[11px] font-semibold text-blue-400">
              {initials}
            </span>
          </div>
          <span className="text-xs text-slate-300 hidden sm:inline">
            {displayName}
          </span>
          <button
            onClick={logout}
            className="text-slate-500 hover:text-slate-300 transition-colors"
            title="Sign out"
          >
            <LogOut className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/*  Layout                                                            */
/* ------------------------------------------------------------------ */

export function Layout() {
  const terminalOpen = useConfigStore((s) => s.terminalOpen);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar />

      {/* Main workspace */}
      <div className="flex flex-1 min-h-0">
        {/* Left sidebar — config form */}
        <aside className="w-96 flex-none bg-slate-900 border-r border-slate-800 overflow-y-auto">
          <Sidebar />
        </aside>

        {/* Right panel — HCL preview */}
        <main className="flex-1 min-w-0 overflow-hidden flex flex-col">
          <div className="flex-1 overflow-y-auto">
            <HclPreview />
          </div>

          {/* Bottom drawer — terminal */}
          {terminalOpen && (
            <div className="h-64 flex-none border-t border-slate-800">
              <TerminalDrawer />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
