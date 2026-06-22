import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  ComposedChart,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Area,
  Legend,
} from "recharts";
import type { ResultData, Viz } from "../types";

const fmt = (n: number) =>
  Math.abs(n) >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)}M`
    : Math.abs(n) >= 1_000
      ? `${(n / 1_000).toFixed(1)}K`
      : `${n}`;

// Dark theme palette
const GRID   = "#334155";
const TICK   = { fill: "#94a3b8", fontSize: 11 };
const BLUE   = "#3b82f6";
const AMBER  = "#f59e0b";
const TOOLTIP_STYLE = {
  backgroundColor: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 8,
  color: "#e2e8f0",
  fontSize: 12,
};

export function BarChartView({ data, viz }: { data: ResultData; viz: Viz }) {
  const rows = data.rows.map((r) => ({
    label: String(r[viz.label_col!] ?? ""),
    value: Number(r[viz.value_col!] ?? 0),
  }));
  return (
    <div>
      <p className="mb-2 text-center text-xs font-semibold text-slate-400 uppercase tracking-wide">
        {viz.label_col} — {viz.value_col}
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 40, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="label" tick={TICK} interval={0} angle={-25} textAnchor="end" height={60} />
          <YAxis tickFormatter={fmt} tick={TICK} />
          <Tooltip
            formatter={(v: number) => [`Rs. ${fmt(v)}`, viz.value_col]}
            contentStyle={TOOLTIP_STYLE}
            cursor={{ fill: "#334155", opacity: 0.5 }}
          />
          <Bar dataKey="value" fill={BLUE} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LineChartView({ data, viz }: { data: ResultData; viz: Viz }) {
  const rows = data.rows.map((r) => ({
    x: String(r[viz.x_col!] ?? ""),
    y: Number(r[viz.y_col!] ?? 0),
  }));
  return (
    <div>
      <p className="mb-2 text-center text-xs font-semibold text-slate-400 uppercase tracking-wide">
        {viz.x_col} vs {viz.y_col}
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="x" tick={TICK} />
          <YAxis tickFormatter={fmt} tick={TICK} />
          <Tooltip
            formatter={(v: number) => [`Rs. ${fmt(v)}`, viz.y_col]}
            contentStyle={TOOLTIP_STYLE}
          />
          <Line type="monotone" dataKey="y" stroke={BLUE} strokeWidth={2.5} dot={{ r: 4, fill: BLUE }} activeDot={{ r: 6 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ForecastChartView({ data, viz }: { data: ResultData; viz: Viz }) {
  const f = viz.forecast!;
  const histX = data.rows.map((r) => String(r[viz.x_col!]));
  const combined: any[] = histX.map((x, i) => ({ x, actual: f.history[i] }));
  f.forecast.forEach((y, i) => {
    combined.push({ x: `+${i + 1}`, forecast: y, lower: f.ci[i]?.lower, upper: f.ci[i]?.upper });
  });
  if (combined.length && f.history.length) {
    combined[f.history.length - 1].forecast = f.history[f.history.length - 1];
  }
  return (
    <div>
      <p className="mb-2 text-center text-xs font-semibold text-slate-400 uppercase tracking-wide">
        Trend Forecast — {viz.y_col}
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={combined} margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="x" tick={TICK} />
          <YAxis tickFormatter={fmt} tick={TICK} />
          <Tooltip formatter={(v: number) => [`Rs. ${fmt(v)}`]} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 11 }} />
          <Area dataKey="upper" stroke="none" fill="#1e3a5f" fillOpacity={0.6} legendType="none" />
          <Area dataKey="lower" stroke="none" fill="#0f172a" fillOpacity={1} legendType="none" />
          <Line type="monotone" dataKey="actual" stroke={BLUE} strokeWidth={2.5} dot={{ r: 3 }} name="Actual" />
          <Line type="monotone" dataKey="forecast" stroke={AMBER} strokeWidth={2.5} strokeDasharray="5 4" dot={{ r: 3 }} name="Forecast" />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-1 text-center text-xs text-slate-500">
        Trend {f.trend_pct_per_period >= 0 ? "▲" : "▼"} {Math.abs(f.trend_pct_per_period)}% per period · forecast in amber
      </p>
    </div>
  );
}

export function KpiCard({ data, viz }: { data: ResultData; viz: Viz }) {
  const row = data.rows[0] ?? {};
  const value = Number(row[viz.value_col!]);
  const label = viz.label && row[viz.label] != null ? String(row[viz.label]) : viz.value_col;
  return (
    <div className="flex flex-col items-center justify-center rounded-xl bg-brand-600/10 border border-brand-600/30 py-8">
      <div className="text-4xl font-bold text-brand-400">Rs. {fmt(value)}</div>
      <div className="mt-2 text-sm font-medium text-slate-400">{label}</div>
    </div>
  );
}
