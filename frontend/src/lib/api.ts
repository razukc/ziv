// Typed client for the SkillForge HTTP API, including the SSE compose
// stream. All requests go through the Next.js dev proxy (/api/* -> :8000).

import type {
  ComposeResponse,
  ExecutionLog,
  ExportedPackage,
  Pipeline,
  Skill,
  ThinkingStep,
  ValidationReport,
} from "./types";

async function postJson<T>(url: string, body: unknown, failMessage?: string): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(failMessage ?? `api error (${res.status})`);
  return res.json();
}

export function fetchSkills(): Promise<Skill[]> {
  return fetch("/api/skills").then(res => (res.ok ? res.json() : Promise.resolve([])));
}

/** Fetch a stored pipeline by its share-link id. */
export async function fetchPipeline(id: string): Promise<Pipeline> {
  const res = await fetch(`/api/pipeline/${id}`);
  if (!res.ok) throw new Error("not found");
  const data = await res.json();
  return data.pipeline;
}

export interface ExportPayload {
  task: string;
  robot: string;
  /** Omitted when re-exporting an edited inline pipeline (forces the backend
   * to use the inline payload instead of the stale stored pipeline). */
  pipeline_id?: string;
  pipeline?: Pipeline | null;
}

export function exportPackage(payload: ExportPayload): Promise<ExportedPackage> {
  return postJson<ExportedPackage>("/api/pipeline/export", payload, "export failed");
}

export function validatePackageRemote(
  files: Record<string, string>,
  package_name: string
): Promise<ValidationReport> {
  return postJson<ValidationReport>("/api/pipeline/validate", { files, package_name }, "validation failed");
}

// --- compose stream (SSE) --------------------------------------------------

export interface ComposeStreamHandlers {
  onThinking?: (step: Pick<ThinkingStep, "content" | "step" | "total">) => void;
  onPipeline?: (pipeline: Pipeline, pipelineId: string) => void;
  onExplanation?: (text: string) => void;
  onLog?: (log: Pick<ExecutionLog, "content" | "status" | "step" | "total" | "skill_id">) => void;
}

export interface ComposeStreamResult extends ComposeResponse {
  pipelineId: string;
}

/**
 * Open the POST /api/compose/stream request. Resolves once response headers
 * arrive (i.e. after the server has the request), so the caller can apply a
 * header-wait timeout before consuming events.
 */
export async function startComposeStream(task: string, robot: string, signal?: AbortSignal): Promise<Response> {
  return fetch("/api/compose/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, robot }),
    signal,
  });
}

/** Read SSE events from an opened compose stream until `done`. */
export async function readComposeStream(
  res: Response,
  handlers: ComposeStreamHandlers = {}
): Promise<ComposeStreamResult> {
  const reader = res.body?.getReader();
  const decoder = new TextDecoder();
  if (!reader) throw new Error("no response stream — server returned empty body");

  let pipeline: Pipeline | null = null;
  let explanation = "";
  let pipelineId = "";
  const onPipeline = handlers.onPipeline;
  const onLog = handlers.onLog;
  const onThinking = handlers.onThinking;
  const onExplanation = handlers.onExplanation;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    for (const line of decoder.decode(value).split("\n")) {
      if (!line.startsWith("data: ")) continue;
      let event: { type?: string } & Record<string, unknown>;
      try {
        event = JSON.parse(line.slice(6));
      } catch {
        continue; // malformed event — skip and keep streaming
      }
      if (typeof event.type !== "string") continue;

      switch (event.type) {
        case "thinking":
          if (typeof event.content === "string") {
            onThinking?.({ content: event.content, step: Number(event.step) || 1, total: Number(event.total) || 5 });
          }
          break;
        case "pipeline":
          if (event.content && typeof event.content === "object") {
            pipeline = event.content as Pipeline;
            if (typeof event.pipeline_id === "string") pipelineId = event.pipeline_id;
            if (pipeline) onPipeline?.(pipeline, pipelineId);
          }
          break;
        case "explanation":
          if (typeof event.content === "string") {
            explanation = event.content;
            onExplanation?.(explanation);
          }
          break;
        case "log":
          if (typeof event.content === "string") {
            onLog?.({
              content: event.content,
              status: (event.status as ExecutionLog["status"]) || "running",
              step: Number(event.step) || 1,
              total: Number(event.total) || 1,
              skill_id: String(event.skill_id || "unknown"),
            });
          }
          break;
        case "error":
          throw new Error(String(event.content || "pipeline failed"));
        case "done":
          if (typeof event.pipeline_id === "string") pipelineId = event.pipeline_id;
          if (!pipeline) throw new Error("stream ended without pipeline data");
          return { pipeline, explanation, pipelineId };
      }
    }
  }
  if (!pipeline) throw new Error("stream ended without pipeline data");
  return { pipeline, explanation, pipelineId };

}
