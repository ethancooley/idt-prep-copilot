export type Severity = "high" | "medium" | "low";
export type Verdict = "supported" | "partially_supported" | "unsupported";

export interface BriefItem {
  category: string;
  severity: Severity;
  statement: string;
  citations: string[];
  verdict?: Verdict | null;
  verifier_note?: string | null;
}

export interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  by: "model" | "safety_net";
}

export interface Brief {
  participant_id: string;
  participant_name: string;
  review_date: string;
  window_start: string;
  headline: string;
  items: BriefItem[];
  questions_for_team: string[];
  removed_claims: BriefItem[];
  run: {
    sample?: boolean;
    models?: Record<string, string>;
    draft_attempts?: number;
    tool_calls?: ToolCall[];
    llm_calls?: number;
    cost_usd?: number;
    seconds?: number;
    by_step?: Record<string, { calls: number; cost_usd: number }>;
  };
}

export interface Note {
  id: string;
  note_date: string;
  author_role: string;
  note_type: string;
  text: string;
}

export interface ParticipantSummary {
  id: string;
  first_name: string;
  last_name: string;
  sex: string;
  city: string;
  age: number;
  review_date: string;
  window_start: string;
  enrollment_date: string;
  conditions: { description: string; onset: string }[];
  active_medications: { description: string; start_date: string; note: string | null }[];
  allergies: { description: string; reaction: string | null }[];
}

export interface Vitals {
  since: string;
  weight?: {
    readings: { obs_date: string; kg: number; lb: number }[];
    change?: { from: string; to: string; kg: number; lb: number; percent: number };
  };
  blood_pressure?: {
    readings: { obs_date: string; systolic: number; diastolic: number }[];
    elevated_count: number;
    elevated_threshold: string;
  };
}

export interface Bundle {
  participant: ParticipantSummary;
  brief: Brief;
  notes: Note[];
  records: {
    "record:vitals": Vitals;
    "record:encounters": { id: string; start_date: string; encounter_class: string; description: string; reason: string | null }[];
    "record:medications": {
      since: string;
      started: { description: string; start_date: string; stop_date: string | null; note: string | null }[];
      stopped: { description: string; start_date: string; stop_date: string | null; note: string | null }[];
    };
    "record:immunizations": {
      records_last_two_years: { imm_date: string; description: string }[];
      flu_season_start: string;
      flu_vaccine_this_season: boolean;
    };
  };
  live?: { runs_left_today: number };
}

export interface Evaluation {
  participants: number;
  recall: number;
  high_severity_recall: number;
  perfect_briefs: number;
  distractor_violations: number;
  removed_claims: number;
  cost_usd_per_brief: number;
  seconds_median: number;
}

export interface QueueEntry {
  id: string;
  name: string;
  age: number;
  sex: string;
  city: string;
  headline: string;
  counts: Record<Severity, number>;
  flags: string[];
}

export interface Index {
  generated_at: string;
  source: "claude" | "sample";
  review_date: string | null;
  window_start: string | null;
  models: Record<string, string>;
  evaluation: Evaluation | null;
  participants: QueueEntry[];
}
