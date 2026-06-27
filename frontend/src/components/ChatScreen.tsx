import { useCallback, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askStream, fetchSessions, fetchSessionTurns } from "../api";
import { useStore } from "../store";
import type { AssistantTurn, SessionInfo, StreamEvent } from "../types";
import Sidebar from "./Sidebar";
import MessageInput from "./MessageInput";
import ExampleQuestions from "./ExampleQuestions";
import ThinkingPanel from "./ThinkingPanel";
import SqlPanel from "./SqlPanel";
import ResultView from "./ResultView";

// Minimal client-side viz detection for restoring history turns
function detectViz(result: any): import("../types").Viz | undefined {
  if (!result?.rows?.length || !result?.columns?.length) return undefined;
  const cols: string[] = result.columns;
  const first = result.rows[0];
  const numericCols = cols.filter((c) => typeof first[c] === "number");
  if (cols.length <= 2 && numericCols.length === 1) {
    return { type: "kpi", value_col: numericCols[0] };
  }
  return { type: "table" };
}

function emptyTurn(question: string): AssistantTurn {
  return { question, thinking: "", sql: "", answer: "", info: [], suggestions: [], streaming: true };
}

export default function ChatScreen() {
  const { model, setModel, thinking, setThinking, sessionId, setSessionId } = useStore();
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loadingSession, setLoadingSession] = useState(false);
  const [editPrefill, setEditPrefill] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refreshSessions = useCallback(() => {
    fetchSessions().then(setSessions).catch(() => {});
  }, []);

  // Smart scroll — only scrolls if the user is already near the bottom.
  function scrollToBottom() {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom < 120) {
      requestAnimationFrame(() => {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      });
    }
  }

  // Force scroll — used only when a new question is submitted.
  function forceScrollToBottom() {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }

  function stop() {
    abortRef.current?.abort();
  }

  function newChat() {
    setSessionId(null);
    setTurns([]);
  }

  async function loadSession(id: string) {
    setSessionId(id);
    setTurns([]);
    setLoadingSession(true);
    try {
      const raw = await fetchSessionTurns(id);
      const loaded: AssistantTurn[] = raw.map((t: any) => ({
        question: t.question,
        thinking: t.thinking || "",
        sql: t.sql || "",
        answer: t.answer || "",
        result: t.result ?? undefined,
        viz: t.result ? detectViz(t.result) : undefined,
        info: [],
        suggestions: [],
        streaming: false,
      }));
      setTurns(loaded);
      scrollToBottom();
    } catch {
      // session load failed — start fresh
    } finally {
      setLoadingSession(false);
    }
  }

  function patchLast(fn: (t: AssistantTurn) => AssistantTurn) {
    setTurns((prev) => {
      if (!prev.length) return prev;
      const copy = [...prev];
      copy[copy.length - 1] = fn(copy[copy.length - 1]);
      return copy;
    });
  }

  // Edit a question: remove that turn + all turns after it, pre-fill the input
  function editQuestion(index: number) {
    const q = turns[index].question;
    setTurns((prev) => prev.slice(0, index));
    setEditPrefill(q);
  }

  async function send(question: string) {
    setBusy(true);
    setTurns((prev) => [...prev, emptyTurn(question)]);
    forceScrollToBottom();

    const controller = new AbortController();
    abortRef.current = controller;

    const handle = (e: StreamEvent) => {
      switch (e.type) {
        case "session":
          setSessionId(e.session_id);
          break;
        case "info":
          patchLast((t) => ({
            ...t,
            info: [...t.info, e.text ?? `${e.stage}: ${(e.tables ?? e.keywords ?? []).join(", ")}`],
          }));
          break;
        case "thinking":
          patchLast((t) => ({ ...t, thinking: t.thinking + e.text }));
          break;
        case "sql_reset":
          patchLast((t) => ({ ...t, sql: "" }));
          break;
        case "sql_token":
          patchLast((t) => ({ ...t, sql: t.sql + e.text }));
          break;
        case "sql":
          patchLast((t) => ({ ...t, sql: e.sql }));
          break;
        case "result":
          patchLast((t) => ({ ...t, result: e.data, viz: e.viz }));
          break;
        case "answer_token":
          patchLast((t) => ({ ...t, answer: t.answer + e.text }));
          break;
        case "answer_done":
          break;
        case "answer":
          patchLast((t) => ({ ...t, answer: e.text }));
          break;
        case "suggestions":
          patchLast((t) => ({ ...t, suggestions: e.questions }));
          break;
        case "error":
          patchLast((t) => ({ ...t, error: e.text, sql: e.sql ?? t.sql }));
          break;
        case "done":
          // Unlock the UI immediately — follow-up suggestions arrive after this
          patchLast((t) => ({ ...t, streaming: false }));
          setBusy(false);
          refreshSessions();
          break;
      }
      scrollToBottom();
    };

    try {
      await askStream({ question, session_id: sessionId, model, thinking }, handle, controller.signal);
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        patchLast((t) => ({ ...t, error: `Connection error: ${String(err)}` }));
      }
    } finally {
      abortRef.current = null;
      // Fallback: ensure busy is cleared even if done event wasn't received
      patchLast((t) => ({ ...t, streaming: false }));
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full bg-slate-950 overflow-hidden">
      <Sidebar sessions={sessions} onNewChat={newChat} onLoadSession={loadSession} refresh={refreshSessions} />

      <div className="flex flex-1 flex-col overflow-hidden">
        <Header
          model={model} setModel={setModel}
          thinking={thinking} setThinking={setThinking}
          busy={busy} onStop={stop}
        />

        {/* Progress bar */}
        <div className="relative h-0.5 bg-slate-800">
          {busy && (
            <div className="absolute inset-0 animate-progress bg-gradient-to-r from-brand-600 via-blue-400 to-brand-600 bg-[length:200%_100%]" />
          )}
        </div>

        <div ref={scrollRef} className="conversation-scroll flex-1 overflow-x-auto px-4 py-6 bg-slate-950">
          {loadingSession ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-sm font-medium text-slate-500">Loading conversation…</div>
            </div>
          ) : turns.length === 0 ? (
            <div className="mt-12">
              <ExampleQuestions onPick={send} />
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-6">
              {turns.map((t, i) => (
                <TurnView
                  key={i}
                  turn={t}
                  onSend={send}
                  isLast={i === turns.length - 1}
                  onRetry={t.error ? () => send(t.question) : undefined}
                  onEdit={() => editQuestion(i)}
                />
              ))}
            </div>
          )}
        </div>

        <MessageInput
          onSend={send}
          busy={busy}
          prefill={editPrefill}
          onPrefillConsumed={() => setEditPrefill("")}
        />
      </div>
    </div>
  );
}

function Header({
  model, setModel, thinking, setThinking, busy, onStop,
}: {
  model: "sonnet" | "opus";
  setModel: (m: "sonnet" | "opus") => void;
  thinking: boolean;
  setThinking: (v: boolean) => void;
  busy: boolean;
  onStop: () => void;
}) {
  return (
    <header className="flex items-center gap-3 border-b border-slate-700/60 bg-slate-900/80 backdrop-blur-sm px-4 py-2.5">
      <div className="flex items-center gap-2">
        <div className="relative flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-lg shadow-brand-900/40">
          <span className="text-sm font-bold text-white">A</span>
          {busy && (
            <span className="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-500" />
            </span>
          )}
        </div>
        <div>
          <span className="text-sm font-bold text-white">Alex</span>
          <span className="ml-1.5 text-xs text-slate-500">· SAP B1 Intelligence Assistant</span>
        </div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {/* Stop button — only visible while streaming */}
        {busy && (
          <button
            onClick={onStop}
            className="flex items-center gap-1.5 rounded-lg border border-red-700/60 bg-red-950/40 px-3 py-1.5 text-xs font-semibold text-red-400 transition-colors hover:bg-red-900/50 hover:text-red-300"
          >
            <span className="inline-block h-2 w-2 rounded-sm bg-red-400" />
            Stop
          </button>
        )}
        <div className="flex rounded-lg border border-slate-700 p-0.5 text-xs">
          {(["sonnet", "opus"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setModel(m)}
              className={`rounded-md px-2.5 py-1 font-semibold capitalize transition-colors ${
                model === m ? "bg-brand-600 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        <button
          onClick={() => setThinking(!thinking)}
          className={`rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
            thinking
              ? "border-amber-600/50 bg-amber-950/50 text-amber-400"
              : "border-slate-700 text-slate-500 hover:text-slate-300"
          }`}
        >
          ⚙ Thinking {thinking ? "On" : "Off"}
        </button>
      </div>
    </header>
  );
}

function TurnView({
  turn, onSend, isLast, onRetry, onEdit,
}: {
  turn: AssistantTurn;
  onSend: (q: string) => void;
  isLast: boolean;
  onRetry?: () => void;
  onEdit?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [hovered, setHovered] = useState(false);

  async function copyAnswer() {
    await navigator.clipboard.writeText(turn.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div>
      {/* User message */}
      <div
        className="flex items-center justify-end gap-2"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Edit button — fades in when row is hovered */}
        {onEdit && (
          <button
            onClick={onEdit}
            title="Edit this question"
            className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 transition-all duration-150 hover:bg-slate-800 hover:text-slate-200 ${
              hovered ? "opacity-100" : "opacity-0 pointer-events-none"
            }`}
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
            </svg>
            Edit
          </button>
        )}
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-gradient-to-br from-brand-600 to-brand-700 px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-brand-900/30">
          {turn.question}
        </div>
      </div>

      {/* Assistant response */}
      <div className="mt-3">
        {turn.info.length > 0 && (
          <div className="mb-1.5 text-[11px] font-medium text-slate-600">
            {turn.info[turn.info.length - 1]}
          </div>
        )}

        <ThinkingPanel text={turn.thinking} streaming={turn.streaming && !turn.answer} />
        <SqlPanel sql={turn.sql} streaming={turn.streaming && !turn.result && !turn.answer} />

        {turn.result && turn.viz && <ResultView data={turn.result} viz={turn.viz} />}

        {turn.error && (
          <div className="mt-2 rounded-xl border border-red-800/40 bg-red-950/20 px-4 py-3 backdrop-blur-sm">
            <p className="text-sm font-semibold text-red-400">Something went wrong</p>
            <p className="mt-0.5 text-xs text-red-500/70">{turn.error}</p>
            {onRetry && (
              <button
                onClick={onRetry}
                className="mt-2 rounded-lg border border-red-700/40 px-3 py-1.5 text-xs font-semibold text-red-400 hover:bg-red-900/30 transition-colors"
              >
                Try again
              </button>
            )}
          </div>
        )}

        {/* Glassmorphism answer card + Copy button */}
        {turn.answer && (
          <div className="group relative mt-2">
            <div className="rounded-2xl rounded-bl-sm border border-slate-700/50 bg-slate-800/60 px-5 py-4 shadow-xl shadow-slate-950/40 backdrop-blur-sm ring-1 ring-white/5 prose prose-sm prose-invert max-w-none prose-p:my-1.5 prose-ul:my-1.5 prose-li:my-0.5 prose-strong:font-bold prose-strong:text-white prose-headings:font-bold prose-headings:text-white font-medium text-slate-100 text-sm overflow-x-auto">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ children, ...props }) => (
                    <p {...props}>
                      {children}
                      {turn.streaming && !turn.suggestions.length && (
                        <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-brand-400 align-middle" />
                      )}
                    </p>
                  ),
                  table: ({ children }) => (
                    <div className="my-3 overflow-x-auto rounded-lg border border-slate-700/60">
                      <table className="min-w-full border-collapse text-sm">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => (
                    <thead className="bg-slate-800/80">{children}</thead>
                  ),
                  th: ({ children }) => (
                    <th className="border-b border-slate-700 px-4 py-2.5 text-left text-xs font-bold uppercase tracking-wide text-slate-300 whitespace-nowrap">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border-b border-slate-700/50 px-4 py-2 text-sm text-slate-200 whitespace-nowrap">
                      {children}
                    </td>
                  ),
                  tr: ({ children }) => (
                    <tr className="transition-colors hover:bg-slate-700/30">{children}</tr>
                  ),
                }}
              >{turn.answer}</ReactMarkdown>
            </div>
            {/* Copy button — appears on hover */}
            <button
              onClick={copyAnswer}
              title="Copy answer"
              className="absolute right-3 top-3 hidden rounded-lg border border-slate-600/50 bg-slate-800/80 px-2 py-1 text-[11px] font-medium text-slate-400 backdrop-blur-sm transition-all hover:border-slate-500 hover:text-slate-200 group-hover:flex items-center gap-1"
            >
              {copied ? (
                <><span className="text-green-400">✓</span> Copied</>
              ) : (
                <><span>⧉</span> Copy</>
              )}
            </button>
          </div>
        )}

        {turn.streaming && !turn.thinking && !turn.sql && !turn.answer && (
          <div className="mt-2 flex items-center gap-2 text-sm text-slate-500">
            <span className="inline-flex gap-1">
              <span className="animate-bounce" style={{ animationDelay: "0ms" }}>·</span>
              <span className="animate-bounce" style={{ animationDelay: "150ms" }}>·</span>
              <span className="animate-bounce" style={{ animationDelay: "300ms" }}>·</span>
            </span>
            Alex is thinking…
          </div>
        )}
      </div>
    </div>
  );
}
