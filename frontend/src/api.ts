import type { ExampleQuestion, SessionInfo, StreamEvent } from "./types";

// Vite proxies /api → http://localhost:8000
const BASE = "";

export async function login(username: string, password: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return res.ok;
}

export async function fetchSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${BASE}/api/sessions`);
  if (!res.ok) return [];
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}`, { method: "DELETE" });
  return res.ok;
}

export async function fetchSessionTurns(sessionId: string): Promise<any[]> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/turns`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchExampleQuestions(): Promise<ExampleQuestion[]> {
  const res = await fetch(`${BASE}/api/example-questions`);
  if (!res.ok) return [];
  return res.json();
}

export interface AskBody {
  question: string;
  session_id: string | null;
  model: "sonnet" | "opus";
  thinking: boolean;
}

/**
 * POST /api/ask and consume the SSE stream. EventSource can't POST, so we read
 * the ReadableStream and parse `data: {...}\n\n` frames ourselves.
 */
export async function askStream(
  body: AskBody,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.body) throw new Error("No response stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(6)) as StreamEvent);
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}
