import { useState } from "react";
import { login } from "../api";
import { useStore } from "../store";

export default function LoginScreen() {
  const setAuthed = useStore((s) => s.setAuthed);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("demo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const ok = await login(username, password);
      if (ok) setAuthed(true);
      else setError("Invalid username or password.");
    } catch {
      setError("Could not reach the server. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex h-full items-center justify-center overflow-hidden bg-slate-950">

      {/* Background glow blobs */}
      <div className="absolute left-1/4 top-1/4 h-64 w-64 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand-600/10 blur-3xl" />
      <div className="absolute right-1/4 bottom-1/4 h-48 w-48 translate-x-1/2 translate-y-1/2 rounded-full bg-brand-700/10 blur-3xl" />

      <form
        onSubmit={submit}
        className="relative w-[400px] animate-slide-up rounded-2xl border border-slate-700/50 bg-slate-900/80 p-8 shadow-2xl shadow-slate-950/80 backdrop-blur-sm ring-1 ring-white/5"
      >
        {/* Logo */}
        <div className="mb-7 text-center">
          <div className="relative mx-auto mb-4 flex h-14 w-14 items-center justify-center">
            <div className="absolute inset-0 rounded-2xl bg-brand-600/30 blur-lg" />
            <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-xl ring-1 ring-white/10">
              <span className="text-xl font-bold text-white">A</span>
            </div>
          </div>
          <h1 className="text-xl font-bold text-white">SAP B1 Analytics</h1>
          <p className="mt-1 text-sm text-slate-400">
            Hello! I'm <span className="font-semibold text-slate-300">Alex</span> — your SAP Business Intelligence Assistant
          </p>
        </div>

        {/* Fields */}
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">
              Username
            </label>
            <input
              className="w-full rounded-xl border border-slate-700/60 bg-slate-800/60 px-3.5 py-2.5 text-sm text-white placeholder-slate-600 backdrop-blur-sm transition focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">
              Password
            </label>
            <input
              type="password"
              className="w-full rounded-xl border border-slate-700/60 bg-slate-800/60 px-3.5 py-2.5 text-sm text-white placeholder-slate-600 backdrop-blur-sm transition focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-800/40 bg-red-950/30 px-3 py-2 text-sm font-medium text-red-400">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-xl bg-gradient-to-r from-brand-600 to-brand-700 py-2.5 text-sm font-bold text-white shadow-lg shadow-brand-900/40 transition hover:from-brand-500 hover:to-brand-600 disabled:opacity-50"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Signing in…
            </span>
          ) : (
            "Sign in"
          )}
        </button>

        <p className="mt-5 text-center text-[11px] text-slate-600">
          Techative Pvt Ltd · Powered by SAP Business One
        </p>
      </form>
    </div>
  );
}
