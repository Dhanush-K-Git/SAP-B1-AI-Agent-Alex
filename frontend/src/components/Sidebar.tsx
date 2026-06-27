import { useEffect, useState } from "react";
import type { SessionInfo } from "../types";
import { useStore } from "../store";
import { deleteSession } from "../api";
import DocumentPanel from "./DocumentPanel";

export default function Sidebar({
  sessions,
  onNewChat,
  onLoadSession,
  refresh,
}: {
  sessions: SessionInfo[];
  onNewChat: () => void;
  onLoadSession: (id: string) => void;
  refresh: () => void;
}) {
  const sessionId = useStore((s) => s.sessionId);
  const setSessionId = useStore((s) => s.setSessionId);
  const setAuthed = useStore((s) => s.setAuthed);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    setDeletingId(id);
    try {
      await deleteSession(id);
      // If the deleted session was active, clear it
      if (id === sessionId) {
        setSessionId(null);
      }
      refresh();
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <aside className="flex w-64 flex-col border-r border-slate-700 bg-slate-900">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full rounded-lg bg-brand-600 py-2 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
        >
          + New Chat
        </button>
      </div>

      <div className="flex-1 overflow-auto px-2">
        <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          History
        </p>
        {sessions.length === 0 && (
          <p className="px-2 py-2 text-xs text-slate-500">No conversations yet.</p>
        )}
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`group mb-1 flex items-center rounded-lg transition-colors ${
              s.id === sessionId ? "bg-brand-600/20" : "hover:bg-slate-800"
            }`}
          >
            <button
              onClick={() => onLoadSession(s.id)}
              className={`flex-1 truncate px-2 py-2 text-left text-sm ${
                s.id === sessionId
                  ? "font-medium text-brand-400"
                  : "text-slate-400 group-hover:text-slate-200"
              }`}
              title={s.title}
            >
              {s.title || "Untitled"}
            </button>

            {/* Delete button — visible on hover */}
            <button
              onClick={(e) => handleDelete(e, s.id)}
              disabled={deletingId === s.id}
              title="Delete chat"
              className="mr-1 hidden shrink-0 rounded p-1 text-slate-600 hover:bg-red-900/40 hover:text-red-400 group-hover:flex disabled:opacity-40 transition-colors"
            >
              {deletingId === s.id ? (
                <span className="text-[10px]">…</span>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              )}
            </button>
          </div>
        ))}
      </div>

      {/* Document Upload Section */}
      <div className="border-t border-slate-700 p-3">
        <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Documents (RAG)
        </p>
        <DocumentPanel />
      </div>

      <div className="border-t border-slate-700 p-3">
        <div className="mb-2 px-1 text-[11px] font-semibold text-slate-400">
          SAP B1 Analytics · Alex
        </div>
        <button
          onClick={() => setAuthed(false)}
          className="w-full rounded-lg border border-slate-700 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
