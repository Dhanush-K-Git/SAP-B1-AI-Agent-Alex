import { useState } from "react";

function deduplicateThinking(raw: string): string {
  // Remove consecutive duplicate sentences the model sometimes emits
  const sentences = raw.split(/(?<=[.!?])\s+/);
  const deduped: string[] = [];
  for (const s of sentences) {
    if (s.trim() && s.trim() !== deduped[deduped.length - 1]?.trim()) {
      deduped.push(s);
    }
  }
  return deduped.join(" ");
}

export default function ThinkingPanel({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(false); // collapsed by default
  if (!text && !streaming) return null;
  const displayText = streaming ? text : deduplicateThinking(text);

  return (
    <div className="mt-2 rounded-lg border border-slate-700/60 bg-slate-800/40">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-slate-400 hover:text-slate-200 transition-colors"
      >
        <span className={`text-amber-500 ${streaming ? "animate-pulse" : ""}`}>⚙</span>
        <span>Reasoning</span>
        {streaming && <span className="text-slate-500">· thinking…</span>}
        <span className="ml-auto text-slate-500 text-[10px]">
          {open ? "▾ hide" : "▸ view"}
        </span>
      </button>
      {open && (
        <div className="max-h-64 overflow-auto border-t border-slate-700/50 px-3 py-2">
          <div className="thinking-text text-amber-300/80">{displayText || "…"}</div>
        </div>
      )}
    </div>
  );
}
