import type { Bundle, Index, Note } from "./types";

const base = import.meta.env.BASE_URL;
export const LIVE_API_URL: string | undefined = (import.meta.env.VITE_LIVE_API_URL as string | undefined)?.replace(/\/+$/, "") || undefined;
export const REPO_URL = "https://github.com/ethancooley/idt-prep-copilot";

let indexCache: Promise<Index> | null = null;
export function loadIndex(): Promise<Index> {
  indexCache ??= fetch(`${base}data/index.json`).then((r) => {
    if (!r.ok) throw new Error("The participant list could not be loaded.");
    return r.json();
  });
  return indexCache;
}

export async function loadBundle(id: string): Promise<Bundle> {
  const r = await fetch(`${base}data/p/${encodeURIComponent(id)}.json`);
  if (!r.ok) throw new Error("This participant's brief could not be loaded.");
  return r.json();
}

// ---------------------------------------------------------------- dates

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-19" -> "Oct 19". Parsed by hand so time zones never shift the day. */
export function shortDate(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}

export function longDate(iso: string): string {
  const [y] = iso.split("-");
  return `${shortDate(iso)}, ${y}`;
}

export function dayNumber(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86_400_000;
}

// ---------------------------------------------------------------- vocabulary

export const CATEGORY_LABELS: Record<string, string> = {
  fall: "Fall",
  hospital_or_ed: "ED visit or admission",
  medication_change: "Medication change",
  weight_loss: "Weight loss",
  functional_status: "Daily living",
  cognition: "Cognition",
  psychosocial: "Mood and attendance",
  caregiver: "Caregiver",
  vitals: "Vitals",
  care_plan_due: "Care plan due",
  other: "Other",
};

export type Discipline =
  | "nursing" | "medical" | "therapy" | "social" | "nutrition" | "pharmacy" | "community" | "record";

export const DISCIPLINE_LABELS: Record<Discipline, string> = {
  nursing: "Nursing",
  medical: "Physicians",
  therapy: "Therapy",
  social: "Social work",
  nutrition: "Nutrition",
  pharmacy: "Pharmacy",
  community: "Home and day center",
  record: "Chart record",
};

export function disciplineOf(role: string): Discipline {
  const r = role.toLowerCase();
  if (r.includes("nurse")) return "nursing";
  if (r.includes("physician")) return "medical";
  if (r.includes("therap")) return "therapy";
  if (r.includes("social")) return "social";
  if (r.includes("dietitian")) return "nutrition";
  if (r.includes("pharmac")) return "pharmacy";
  return "community";
}

const SHORT_ROLES: Record<string, string> = {
  "Registered nurse": "RN",
  "Primary care physician": "PCP",
  "Hospital physician": "Hospital",
  "Physical therapist": "PT",
  "Occupational therapist": "OT",
  "Recreation therapist": "Recreation",
  "Social worker": "Social work",
  Dietitian: "Dietitian",
  Pharmacist: "Pharmacist",
  "Home care aide": "Home care",
  "Day center coordinator": "Day center",
  Driver: "Driver",
};

export const shortRole = (role: string) => SHORT_ROLES[role] ?? role;

export const RECORD_LABELS: Record<string, string> = {
  "record:vitals": "Vitals",
  "record:encounters": "Encounters",
  "record:medications": "Medication changes",
  "record:immunizations": "Immunizations",
};

export function citationLabel(cite: string, notes: Map<string, Note>): string {
  if (cite in RECORD_LABELS) return RECORD_LABELS[cite];
  const n = notes.get(cite);
  return n ? `${shortRole(n.author_role)}, ${shortDate(n.note_date)}` : "Missing note";
}

// ---------------------------------------------------------------- evidence highlighting

const STOP = new Set(("with that this from have been their they about after before which while were since " +
  "there would could should into over under more most less than then also only very just when what will " +
  "team note notes today review reviewed").split(" "));

function terms(text: string): Set<string> {
  const words = text.toLowerCase().match(/[a-z]+|\d+(?:\.\d+)?/g) ?? [];
  return new Set(words.filter((w) => (/^\d/.test(w) ? true : w.length >= 4 && !STOP.has(w))));
}

/** Split a note into sentences and mark the ones that share the most terms with a claim. */
export function highlightSentences(text: string, claim: string): { text: string; match: boolean }[] {
  // Split after sentence punctuation followed by a capital, so "96.9 kg" and "Sep 5, 2026" stay whole.
  const sentences = text.split(/(?<=[.!?]["')]?)\s+(?=[A-Z"(])/).map((s, i, all) => (i < all.length - 1 ? `${s} ` : s));
  const want = terms(claim);
  const scores = sentences.map((s) => [...terms(s)].filter((t) => want.has(t)).length);
  const best = Math.max(0, ...scores);
  const threshold = best >= 3 ? best - 1 : best;
  return sentences.map((s, i) => ({ text: s, match: best > 0 && scores[i] >= threshold }));
}

export const pct = (x: number) => `${Math.round(x * 100)}%`;

/** "claude-haiku-5-5" -> "Claude Haiku 5.5"; falls back to a description when no model is known. */
export function modelLabel(id: string | undefined, fallback: string): string {
  if (!id) return fallback;
  return id.replace(/^claude-/, "Claude ").replace(/-(\d+)-(\d+)$/, " $1.$2").replace(/ (\w)/, (_, c: string) => ` ${c.toUpperCase()}`);
}
