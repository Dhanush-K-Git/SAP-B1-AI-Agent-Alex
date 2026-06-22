import { create } from "zustand";

interface AppState {
  authed: boolean;
  setAuthed: (v: boolean) => void;

  model: "sonnet" | "opus";
  setModel: (m: "sonnet" | "opus") => void;

  thinking: boolean;
  setThinking: (v: boolean) => void;

  sessionId: string | null;
  setSessionId: (id: string | null) => void;
}

export const useStore = create<AppState>((set) => ({
  authed: typeof localStorage !== "undefined" && localStorage.getItem("mvp_auth") === "1",
  setAuthed: (v) => {
    if (v) localStorage.setItem("mvp_auth", "1");
    else localStorage.removeItem("mvp_auth");
    set({ authed: v });
  },

  model: "sonnet",
  setModel: (m) => set({ model: m }),

  thinking: true,
  setThinking: (v) => set({ thinking: v }),

  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),
}));
