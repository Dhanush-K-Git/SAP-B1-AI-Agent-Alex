import { useState } from "react";

export default function MessageInput({
  onSend,
  busy,
}: {
  onSend: (q: string) => void;
  busy: boolean;
}) {
  const [text, setText] = useState("");

  function submit() {
    const q = text.trim();
    if (!q || busy) return;
    onSend(q);
    setText("");
  }

  return (
    <div className="border-t border-slate-700 bg-slate-900 p-3">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask Alex about sales, invoices, inventory, customers…"
          className="max-h-40 flex-1 resize-none rounded-xl border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <button
          onClick={submit}
          disabled={busy || !text.trim()}
          className="rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-40 transition-colors"
        >
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
