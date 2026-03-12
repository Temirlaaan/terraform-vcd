import { CircleDot, X, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@/utils/cn";
import { useConfigStore } from "@/store/useConfigStore";
import { useAuth } from "@/auth/useAuth";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function wsUrl(operationId: string, token: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/terraform/${operationId}?token=${encodeURIComponent(token)}`;
}

function classifyLine(line: string): string {
  if (line.startsWith("[stderr]")) return "text-rose-400";
  if (/Plan:|Apply complete|Destroy complete/.test(line)) return "text-emerald-400 font-semibold";
  if (/Error|FAILED|fatal/.test(line)) return "text-rose-400";
  if (/Warning/.test(line)) return "text-amber-400";
  if (line.startsWith("__EXIT:")) return "text-slate-600";
  return "text-slate-300";
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function TerminalDrawer() {
  const toggleTerminal = useConfigStore((s) => s.toggleTerminal);
  const operationId = useConfigStore((s) => s.currentOperationId);
  const planStatus = useConfigStore((s) => s.planStatus);
  const { token } = useAuth();

  const [logs, setLogs] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const clearLogs = useCallback(() => setLogs([]), []);

  /* ---------- WebSocket lifecycle ---------- */
  useEffect(() => {
    if (!operationId || !token) return;

    // Clear previous logs when a new operation starts
    setLogs([]);
    setConnected(false);

    const ws = new WebSocket(wsUrl(operationId, token));
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (event: MessageEvent) => {
      const line = String(event.data);
      setLogs((prev) => [...prev, line]);
    };

    ws.onclose = () => {
      setConnected(false);
    };

    ws.onerror = () => {
      setConnected(false);
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [operationId, token]);

  /* ---------- Auto-scroll ---------- */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  /* ---------- Status display ---------- */
  const statusLabel =
    planStatus === "planning"
      ? "Running plan..."
      : planStatus === "applying"
        ? "Running apply..."
        : planStatus === "planned"
          ? "Plan complete"
          : planStatus === "applied"
            ? "Apply complete"
            : operationId
              ? `Operation ${operationId.slice(0, 8)}`
              : "No active operation";

  const dotColor = connected
    ? "text-emerald-500"
    : operationId
      ? "text-amber-500"
      : "text-slate-600";

  return (
    <div className="flex flex-col h-full bg-[#0d1117]">
      {/* Terminal header */}
      <div className="flex items-center justify-between px-4 py-1.5 bg-slate-900/80 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <CircleDot className={cn("h-3 w-3", dotColor)} />
          <span className="text-xs font-medium text-slate-400">Terminal</span>
          <span className="text-[10px] text-slate-600">{statusLabel}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={clearLogs}
            className="text-slate-600 hover:text-slate-400 transition-colors"
            title="Clear logs"
          >
            <Trash2 className="h-3 w-3" />
          </button>
          <button
            onClick={toggleTerminal}
            className="text-slate-500 hover:text-slate-300 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Terminal body */}
      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs leading-5">
        {logs.length === 0 ? (
          <div className="text-slate-700">
            <p>
              <span className="text-slate-600">$</span> Waiting for terraform
              output...
            </p>
            <p className="mt-1">
              Logs stream in real-time via WebSocket.
            </p>
          </div>
        ) : (
          logs.map((line, i) => (
            <div key={i} className={classifyLine(line)}>
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
