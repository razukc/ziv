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
}

export type Tab = "analysis" | "json" | "thinking" | "logs";
export type Phase = "idle" | "processing" | "results";
