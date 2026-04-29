import {
  Cloud,
  ChevronDown,
  Terminal as TerminalIcon,
  LogOut,
  LayoutGrid,
  ArrowLeftRight,
  FolderOpen,
  Settings,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/utils/cn";
import { useConfigStore } from "@/store/useConfigStore";
import { useAuth } from "@/auth/useAuth";
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
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("")
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 2);

  return (
    <header className="h-14 flex-none flex items-center justify-between gap-4 bg-clr-header border-b border-[#283845] px-4">
      {/* Left — branding */}
      <div className="flex items-center gap-3">
        <Cloud className="h-5 w-5 text-white" />
        <span className="text-white font-semibold tracking-tight text-sm">
          Terraform VCD Dashboard
        </span>
        <span className="text-[10px] font-medium text-clr-action-light bg-white/10 px-1.5 py-0.5 rounded">
          v0.1
        </span>
      </div>

      {/* Center — environment switcher */}
      <button className="flex items-center gap-1.5 text-xs text-white/80 bg-white/10 border border-white/20 rounded-md px-3 py-1.5 hover:border-white/40 transition-colors">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        vcd-prod-01
        <ChevronDown className="h-3 w-3 text-white/60" />
      </button>

      {/* Right — actions & user */}
      <div className="flex items-center gap-2">
        <button
          onClick={toggleTerminal}
          className={cn(
            "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border transition-colors",
            terminalOpen
              ? "bg-white/20 border-white/30 text-white"
              : "bg-white/10 border-white/20 text-white/70 hover:border-white/40"
          )}
        >
          <TerminalIcon className="h-3.5 w-3.5" />
          Terminal
        </button>

        {/* User avatar + name */}
        <div className="flex items-center gap-2 ml-1">
          <div className="h-8 w-8 rounded-full bg-white/15 border border-white/25 flex items-center justify-center">
            <span className="text-[11px] font-semibold text-white">
              {initials}
            </span>
          </div>
          <span className="text-xs text-white/80 hidden sm:inline">
            {displayName}
          </span>
          <button
            onClick={logout}
            className="text-white/50 hover:text-white transition-colors"
            aria-label="Sign out"
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
/*  NavSidebar                                                        */
/* ------------------------------------------------------------------ */

const navItems = [
  { to: "/", icon: LayoutGrid, label: "Service Catalog", end: true },
  { to: "/migration", icon: ArrowLeftRight, label: "Migration" },
  { to: "/deployments", icon: FolderOpen, label: "My Deployments" },
  { to: "/settings", icon: Settings, label: "Settings" },
] as const;

function NavSidebar() {
  return (
    <nav className="w-56 flex-none bg-clr-near-white border-r border-clr-border py-3 flex flex-col gap-0.5" aria-label="Main navigation">
      {navItems.map(({ to, icon: Icon, label, ...rest }) => (
        <NavLink
          key={to}
          to={to}
          end={"end" in rest}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors border-l-2",
              isActive
                ? "bg-white text-clr-action font-medium border-clr-action"
                : "text-clr-text-secondary hover:bg-white hover:text-clr-text border-transparent"
            )
          }
        >
          <Icon className="h-4 w-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

/* ------------------------------------------------------------------ */
/*  Layout                                                            */
/* ------------------------------------------------------------------ */

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

function AuthDisabledBanner() {
  if (!AUTH_DISABLED) return null;
  return (
    <div className="flex-none bg-amber-500 text-amber-950 text-center text-xs font-semibold py-1 px-3 border-b border-amber-700">
      ⚠ AUTH DISABLED — dev mode. All requests run as anonymous admin. Refused on production builds.
    </div>
  );
}

export function Layout() {
  const terminalOpen = useConfigStore((s) => s.terminalOpen);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <AuthDisabledBanner />
      <TopBar />

      {/* Main workspace */}
      <div className="flex flex-1 min-h-0">
        {/* Left nav sidebar */}
        <NavSidebar />

        {/* Content area */}
        <main className="flex-1 min-w-0 overflow-hidden flex flex-col">
          <div className="flex-1 overflow-y-auto flex flex-col">
            <Outlet />
          </div>

          {/* Bottom drawer — terminal */}
          {terminalOpen && (
            <div className="h-64 flex-none border-t border-clr-border">
              <TerminalDrawer />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
