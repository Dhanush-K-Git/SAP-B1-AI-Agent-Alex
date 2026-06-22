export type StreamEvent =
  | { type: "session"; session_id: string }
  | { type: "info"; stage?: string; intent?: string; keywords?: string[]; tables?: string[]; joins?: number; text?: string }
  | { type: "thinking"; text: string }
  | { type: "sql_token"; text: string }
  | { type: "sql"; sql: string }
  | { type: "result"; data: ResultData; viz: Viz }
  | { type: "answer"; text: string }
  | { type: "answer_token"; text: string }
  | { type: "answer_done" }
  | { type: "sql_reset" }
  | { type: "suggestions"; questions: string[] }
  | { type: "error"; text: string; sql?: string }
  | { type: "done"; session_id: string };

export interface ResultData {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
}

export interface Forecast {
  history: number[];
  forecast: number[];
  slope: number;
  trend_pct_per_period: number;
  ci: { lower: number; upper: number }[];
}

export interface Viz {
  type: "kpi" | "bar" | "line" | "forecast" | "table";
  label?: string | null;
  value_col?: string;
  label_col?: string;
  x_col?: string;
  y_col?: string;
  forecast?: Forecast;
}

export interface AssistantTurn {
  question: string;
  thinking: string;
  sql: string;
  answer: string;
  result?: ResultData;
  viz?: Viz;
  error?: string;
  info: string[];
  suggestions: string[];
  streaming: boolean;
}

export interface ExampleQuestion {
  domain: string;
  question: string;
  tool: string;
}

export interface SessionInfo {
  id: string;
  title: string;
  created_at: string;
}
