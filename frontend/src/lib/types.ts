// Shared domain types for the SkillForge frontend.

export interface Subtask {
  order: number;
  name: string;
  description: string;
  skill_id: string;
  estimated_cost_usd: number;
  gpu_required: boolean;
}

export interface Pipeline {
  task: string;
  robot: string;
  task_type: string;
  subtasks: Subtask[];
  total_estimated_cost_usd: number;
  estimated_time_minutes: number;
  risk_assessment: string;
  notes: string;
}

export interface ComposeResponse {
  pipeline: Pipeline;
  explanation: string;
}

/** Per-phase wall times of a live compose, from the stream's done event. */
export interface ComposePhases {
  /** Wall time of the decompose LLM round-trip (incl. its retry backoff). */
  decompose: number;
  /** Wall time of the explanation LLM round-trip (incl. its retry backoff). */
  explain: number;
  /** Wall time of the (simulated) execution-log stream. */
  logs: number;
}

export interface ThinkingStep {
  content: string;
  step: number;
  total: number;
  timestamp: number;
}

export interface ExecutionLog {
  content: string;
  status: "running" | "completed" | "failed";
  step: number;
  total: number;
  skill_id: string;
  timestamp: number;
}

export interface Skill {
  id: string;
  name: string;
  product: string;
  description: string;
  tags: string[];
  gpu_required: boolean;
  estimated_cost_usd: number;
}

export interface ValidationIssue {
  file: string;
  message: string;
}

export interface ValidationReport {
  valid: boolean;
  score: number;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  info: ValidationIssue[];
}

export interface ExportedPackage {
  package_name: string;
  /** Present on real (backend) exports; mock-mode exports omit them. */
  pipeline_hash?: string;
  pipeline_id?: string;
  files: Record<string, string>;
  metadata: Record<string, unknown>;
}

/** One variation step, tagged with how the seed treated it. */
export interface AdaptationEntry {
  order: number;
  name: string;
  skill_id: string;
  badge: "still-applies" | "reworded" | "new";
  note: string;
}

/** An original-plan step the variation dropped, with the reason why. */
export interface DroppedEntry {
  order: number;
  name: string;
  skill_id: string;
  reason: string;
}

/** Why a seeded variation differs from the plan it was composed from. */
export interface AdaptationReport {
  fromRobot: string;
  toRobot: string;
  /** Every step of the variation, with how it relates to the original. */
  steps: AdaptationEntry[];
  /** Original steps absent from the variation (computed from the seed). */
  dropped: DroppedEntry[];
}

export type PipelineSource = "mock" | "live";

export interface HistoryItem {
  id: string;
  task: string;
  robot: string;
  result: ComposeResponse;
  timestamp: number;
  /** Where the pipeline's durable copy lives: mock pipelines exist only in
   *  this browser (persisted to localStorage); live pipelines carry a
   *  Redis-backed pipeline id so the store is the source of truth. */
  kind: PipelineSource;
  /** Redis-backed pipeline id for live entries (share link / re-export). */
  pipelineId?: string;
  /** Variation provenance: how this pipeline was adapted from its seed, so
   *  reopening the entry can show the adaptation notes again. */
  adaptation?: AdaptationReport | null;
  /** Live-only: wall time + retries of the compose that produced this entry,
   *  so a reopened slow pipeline still shows how long it took. */
  composeStats?: { seconds: number; retries: number; phases: ComposePhases } | null;
  /** Verdict of the last simulation dry-run of this entry's pipeline, so a
   *  reopened pipeline shows its test result without re-running. */
  dryrun?: DryRunRecord | null;
}

/** Completed simulation dry-run, persisted with history. Everything needed
 *  to reproduce the run is here: same pipeline + same seed = same verdicts
 *  (deterministic planner), so a reopened pipeline renders the stored result
 *  instantly instead of replaying. */
export interface DryRunRecord {
  /** Scenario seed the run used. */
  seed: number;
  /** Compressed replay wall time of the completed run, in seconds. */
  elapsedSec: number;
  /** Per-step verdicts, aligned with the pipeline's subtasks at run time. */
  verdicts: ("pass" | "fail")[];
}

export type Tab = "analysis" | "json" | "thinking" | "logs";
export type Phase = "idle" | "processing" | "results";
