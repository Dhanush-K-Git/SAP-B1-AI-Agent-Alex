import { useState } from "react";
import type { ResultData, Viz } from "../types";
import { BarChartView, ForecastChartView, KpiCard, LineChartView } from "./Charts";

type ChartMode = "bar" | "line" | "table" | "forecast" | "kpi";

// ── Feature 4: Color-coded status badges ─────────────────────────────────────
const STATUS_STYLES: Record<string, string> = {
  o:       "bg-emerald-900/40 text-emerald-400 border-emerald-700/50",   // Open
  open:    "bg-emerald-900/40 text-emerald-400 border-emerald-700/50",
  c:       "bg-slate-700/40 text-slate-400 border-slate-600/50",         // Closed
  closed:  "bg-slate-700/40 text-slate-400 border-slate-600/50",
  pending: "bg-amber-900/40 text-amber-400 border-amber-700/50",
  p:       "bg-amber-900/40 text-amber-400 border-amber-700/50",
  a:       "bg-blue-900/40 text-blue-400 border-blue-700/50",            // Active
  active:  "bg-blue-900/40 text-blue-400 border-blue-700/50",
  cancelled:"bg-red-900/40 text-red-400 border-red-700/50",
  canceled: "bg-red-900/40 text-red-400 border-red-700/50",
};

const STATUS_LABELS: Record<string, string> = {
  o: "Open", c: "Closed", p: "Pending", a: "Active",
};

function StatusBadge({ value }: { value: string }) {
  const key = value.toLowerCase();
  const style = STATUS_STYLES[key];
  if (!style) return <span className="font-medium text-slate-200">{value}</span>;
  const label = STATUS_LABELS[key] || value;
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${style}`}>
      {label}
    </span>
  );
}

const STATUS_COL = /status|docstatus|state|stage/i;

function isStatusValue(col: string, val: unknown): boolean {
  if (!STATUS_COL.test(col)) return false;
  if (typeof val !== "string") return false;
  return val.toLowerCase() in STATUS_STYLES;
}

function formatCell(col: string, v: unknown): React.ReactNode {
  if (v == null) return <span className="text-slate-600">—</span>;
  if (isStatusValue(col, v)) return <StatusBadge value={String(v)} />;
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}

// ── Feature 3: Chart toolbar ──────────────────────────────────────────────────
export default function ResultView({ data, viz }: { data: ResultData; viz: Viz }) {
  const [mode, setMode] = useState<ChartMode>(viz.type as ChartMode);
  const [showTable, setShowTable] = useState(false);

  const canBar  = !!viz.label_col && !!viz.value_col;
  const canLine = !!viz.x_col && !!viz.y_col;
  const canChart = canBar || canLine;

  const chart =
    mode === "bar"      && canBar  ? <BarChartView data={data} viz={viz} /> :
    mode === "line"     && canLine ? <LineChartView data={data} viz={viz} /> :
    mode === "forecast" && canLine ? <ForecastChartView data={data} viz={viz} /> :
    mode === "kpi"                 ? <KpiCard data={data} viz={viz} /> :
    null;

  const showChart = chart && mode !== "table";

  return (
    <div className="mt-2 overflow-hidden rounded-xl border border-slate-700/50 bg-slate-800/40 backdrop-blur-sm">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-slate-700/40 px-3 py-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          {data.row_count} row{data.row_count !== 1 ? "s" : ""}
          {data.truncated ? " (truncated)" : ""}
        </span>

        {/* ── Feature 3: View switcher ── */}
        {canChart && (
          <div className="flex items-center gap-1 rounded-lg border border-slate-700/50 bg-slate-900/60 p-0.5 text-[11px]">
            {canBar && (
              <ToolbarBtn active={mode === "bar"} onClick={() => setMode("bar")} label="Bar" icon="▐▌" />
            )}
            {canLine && (
              <ToolbarBtn active={mode === "line"} onClick={() => setMode("line")} label="Line" icon="╱" />
            )}
            <ToolbarBtn active={mode === "table"} onClick={() => setMode("table")} label="Table" icon="≡" />
          </div>
        )}
      </div>

      {/* Chart */}
      {showChart && (
        <div className="p-3 pb-1">
          {chart}
        </div>
      )}

      {/* Toggle raw table under chart */}
      {showChart && (
        <button
          onClick={() => setShowTable(!showTable)}
          className="px-3 pb-2 text-xs font-medium text-brand-400 hover:text-brand-300 transition-colors"
        >
          {showTable ? "Hide" : "Show"} data table
        </button>
      )}

      {/* Data table */}
      {(mode === "table" || showTable) && <DataTable data={data} />}
    </div>
  );
}

function ToolbarBtn({
  active, onClick, label, icon,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1 rounded-md px-2.5 py-1 font-semibold transition-colors ${
        active
          ? "bg-brand-600 text-white"
          : "text-slate-400 hover:text-slate-200"
      }`}
    >
      <span className="text-[10px]">{icon}</span>
      {label}
    </button>
  );
}

function DataTable({ data }: { data: ResultData }) {
  if (!data.rows.length)
    return <p className="px-3 pb-3 text-sm font-medium text-slate-500">No rows returned.</p>;

  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-slate-900/90 backdrop-blur-sm">
          <tr>
            {data.columns.map((c) => (
              <th key={c} className="border-b border-slate-700/50 px-3 py-2 font-bold text-slate-300 uppercase tracking-wide text-[11px]">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr
              key={i}
              className={`border-b border-slate-700/20 transition-colors hover:bg-slate-700/20 ${
                i % 2 ? "bg-slate-800/20" : ""
              }`}
            >
              {data.columns.map((c) => (
                <td key={c} className="px-3 py-2 font-medium text-slate-200">
                  {formatCell(c, row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
