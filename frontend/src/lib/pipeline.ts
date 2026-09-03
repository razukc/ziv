// Pure helpers for pipeline data: task validation, mock composition,
// edit re-computation, and progress/status derivation. No React here, so the
// same rules are exercised by unit tests and kept out of the component.

import { MOCK_PIPELINES } from "./mock-data";
import { plainOverview } from "./plain";
import type { ComposeResponse, ExecutionLog, Pipeline, Subtask, ThinkingStep } from "./types";

export const DEFAULT_TASK = "Pick up the red block from the table";

export function robotSlug(robot: string): string {
  return robot.replace("unitree-", "").replace("1x-", "neo-");
}

export function validateTask(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (trimmed.length < 5) return "task too short — describe what the robot should do";
  if (trimmed.length > 500) return "task too long — keep it under 500 characters";
  return "";
}

// --- mock mode (full demo without the backend) -----------------------------

export function buildMockResult(task: string, robot: string): ComposeResponse {
  const mock = MOCK_PIPELINES[robot] || MOCK_PIPELINES["unitree-g1"];
  return {
    pipeline: {
      task: task || DEFAULT_TASK,
      robot,
      task_type: mock.task_type,
      subtasks: mock.subtasks,
      total_estimated_cost_usd: mock.total,
      estimated_time_minutes: mock.time,
      risk_assessment: mock.risk,
      notes: mock.notes,
    },
    // Plain-words overview instead of the canned engineering summary, so the
    // mock demo reads clearly to non-engineers. Live (backend) composes keep
    // the model's own explanation.
    explanation: plainOverview(mock.task_type, mock.total, mock.risk),
  };
}

export function mockThinking(robot: string): ThinkingStep[] {
  return (MOCK_PIPELINES[robot] || MOCK_PIPELINES["unitree-g1"]).thinking;
}

export function mockLogs(task: string, robot: string): ExecutionLog[] {
  const mock = MOCK_PIPELINES[robot] || MOCK_PIPELINES["unitree-g1"];
  return mock.logs(task);
}

export function mockPipelineId(robot: string): string {
  return `mock-${robotSlug(robot)}-${Date.now().toString(36).slice(-6)}`;
}

// --- human editing: reorder/remove steps -----------------------------------

/** Renumber subtasks 1..n and recompute cost/time from `base`. */
export function recomputePipeline(base: Pipeline, subs: Subtask[]): Pipeline {
  const ordered = subs.map((s, i) => ({ ...s, order: i + 1 }));
  return {
    ...base,
    subtasks: ordered,
    total_estimated_cost_usd:
      Math.round(ordered.reduce((sum, s) => sum + (s.estimated_cost_usd || 0), 0) * 100) / 100,
    estimated_time_minutes: Math.max(
      1,
      Math.round((base.estimated_time_minutes * ordered.length) / base.subtasks.length)
    ),
  };
}

// --- execution progress (derived from the streamed log events) -------------

export function computeProgress(logs: ExecutionLog[]) {
  if (logs.length === 0) return { completed: 0, total: 0, percentage: 0, runningStep: 0 };
  const completedSteps = new Set<number>();
  let runningStep = 0;
  for (const log of logs) {
    if (log.status === "completed") completedSteps.add(log.step);
    else if (log.status === "running") runningStep = log.step;
  }
  const total = logs[0]?.total || 0;
  const completed = completedSteps.size;
  const percentage = total > 0 ? (completed / total) * 100 : 0;
  return { completed, total, percentage, runningStep };
}

export function stepStatus(logs: ExecutionLog[], stepNum: number): "completed" | "running" | "pending" {
  const stepLogs = logs.filter(l => l.step === stepNum);
  if (stepLogs.length === 0) return "pending";
  const lastLog = stepLogs[stepLogs.length - 1];
  if (lastLog.status === "completed") return "completed";
  if (lastLog.status === "running") return "running";
  return "pending";
}

export function logsForStep(logs: ExecutionLog[], stepNum: number): ExecutionLog[] {
  return logs.filter(l => l.step === stepNum);
}

export function costIncurred(logs: ExecutionLog[], pipeline: Pipeline): number {
  const completedSteps = new Set<number>();
  for (const log of logs) {
    if (log.status === "completed") completedSteps.add(log.step);
  }
  return pipeline.subtasks
    .filter(st => completedSteps.has(st.order))
    .reduce((sum, st) => sum + st.estimated_cost_usd, 0);
}
