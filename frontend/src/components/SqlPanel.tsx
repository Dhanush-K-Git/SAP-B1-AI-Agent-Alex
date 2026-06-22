import { useState } from "react";

export default function SqlPanel({ sql, streaming }: { sql: string; streaming?: boolean }) {
  const [open, setOpen] = useState(false); // collapsed by default
  const [copied, setCopied] = useState(false);
  if (!sql) return null;

  async function copy() {
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="mt-2 rounded-lg border border-slate-700/60 bg-slate-800/40">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          onClick={() => setOpen(!open)}
          className="flex flex-1 items-center gap-2 text-xs font-medium text-slate-400 hover:text-slate-200 transition-colors"
        >
          <span className="text-slate-500">📋</span>
          <span>Generated SQL</span>
          {streaming && <span className="text-slate-600">· writing…</span>}
          <span className="ml-2 text-[10px] text-slate-500">{open ? "▾ hide" : "▸ view"}</span>
        </button>
        {open && (
          <button
            onClick={copy}
            className="rounded bg-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-600 transition-colors"
          >
            {copied ? "Copied ✓" : "Copy"}
          </button>
        )}
      </div>
      {open && (
        <pre className="max-h-72 overflow-auto border-t border-slate-700/50 px-3 py-2 text-[12.5px] leading-relaxed text-emerald-300">
          <code>{sql}</code>
        </pre>
      )}
    </div>
  );
}
