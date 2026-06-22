import { useEffect, useState } from "react";
import { fetchExampleQuestions } from "../api";
import type { ExampleQuestion } from "../types";

export default function ExampleQuestions({ onPick }: { onPick: (q: string) => void }) {
  const [items, setItems] = useState<ExampleQuestion[]>([]);

  useEffect(() => {
    fetchExampleQuestions().then(setItems).catch(() => setItems([]));
  }, []);

  const fallback = [
    { domain: "Sales",     question: "Who are the top 10 customers by sales quotation in the last 12 months?" },
    { domain: "Sales",     question: "Show the monthly sales quotation trend for the last 12 months." },
    { domain: "Purchase",  question: "Who are the top 10 vendors by purchase order in the last 12 months?" },
    { domain: "Purchase",  question: "Show the monthly purchase order trend for the last 12 months." },
    { domain: "Finance",   question: "Who are the top 10 customers by incoming payment in the last 12 months?" },
    { domain: "Finance",   question: "Show the monthly incoming payment trend for the last 12 months." },
    { domain: "Inventory", question: "Which items are low on stock (below 10 units)?" },
    { domain: "Inventory", question: "Break down inventory goods receipts by status." },
  ];

  const display = items.length ? items.slice(0, 8) : fallback;

  return (
    <div className="mx-auto max-w-2xl px-4 animate-slide-up">

      {/* ── Hero section ── */}
      <div className="mb-8 text-center">
        {/* Glowing avatar */}
        <div className="relative mx-auto mb-4 flex h-16 w-16 items-center justify-center">
          <div className="absolute inset-0 rounded-2xl bg-brand-600 opacity-30 blur-xl" />
          <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-2xl shadow-brand-900/60 ring-1 ring-white/10">
            <span className="text-2xl font-bold text-white">A</span>
          </div>
        </div>

        <h1 className="text-2xl font-bold text-white">Hello! I'm Alex</h1>
        <p className="mt-1.5 text-sm text-slate-400">
          Your SAP Business One Intelligence Assistant at <span className="font-semibold text-slate-300">Techative Pvt Ltd</span>
        </p>

        {/* Divider with glow */}
        <div className="relative mx-auto mt-5 mb-6 h-px w-48">
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-brand-500/60 to-transparent" />
        </div>

        <p className="text-xs font-semibold uppercase tracking-widest text-slate-600">
          Try asking me
        </p>
      </div>

      {/* ── Example question cards ── */}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {display.map((it, i) => (
          <button
            key={i}
            onClick={() => onPick(it.question)}
            style={{ animationDelay: `${i * 40}ms` }}
            className="group relative overflow-hidden rounded-xl border border-slate-700/50 bg-slate-800/50 px-4 py-3.5 text-left backdrop-blur-sm transition-all duration-200 hover:border-brand-500/50 hover:bg-slate-700/60 hover:shadow-lg hover:shadow-brand-900/20 animate-fade-in"
          >
            {/* Hover glow */}
            <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-brand-600/0 to-brand-600/0 opacity-0 transition-opacity duration-200 group-hover:from-brand-600/5 group-hover:to-transparent group-hover:opacity-100" />

            <span className="relative mb-1.5 block text-[10px] font-bold uppercase tracking-widest text-brand-400">
              {it.domain}
            </span>
            <span className="relative text-sm font-medium text-slate-300 group-hover:text-white transition-colors">
              {it.question}
            </span>

            {/* Arrow indicator */}
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-700 opacity-0 transition-all duration-200 group-hover:opacity-100 group-hover:translate-x-0.5 group-hover:text-brand-400">
              →
            </span>
          </button>
        ))}
      </div>

      {/* Bottom hint */}
      <p className="mt-6 text-center text-[11px] text-slate-700">
        Ask anything about your SAP B1 data — sales, invoices, inventory, finance
      </p>
    </div>
  );
}
