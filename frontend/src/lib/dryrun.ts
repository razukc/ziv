// Simulation dry-run planner: turns a composed pipeline into a deterministic,
// metadata-driven replay schedule with per-step simulated pass/fail verdicts.
// No React here, so the rules are exercised by browser E2E tests and kept out
// of the component.
//
// Honest framing: this is a STRUCTURAL + SEEDED replay, not a real simulator.
//  - Structural checks derive from skill metadata (robot anatomy, step
//    ordering rules) and are deterministic: a plan that asks an armless robot
//    to train an arm policy, or validates before anything was trained, fails
//    the same way every time. This catches edited/shared pipelines that drift
//    — the same job the backend's capability gate does at compose time.
//  - Each remaining step also carries a small seeded execution risk (training
//    can diverge, validation can fall short) so the replay reads like a real
//    run. Same plan + same seed = same outcome; "new scenario" rerolls.
//
// Canonical sources: robot anatomy mirrors agent/robot_registry.py and skill
// requirements mirror agent/skill_registry.py. Keep them in sync when either
// registry changes.

import type { Pipeline } from "./types";

// --- metadata mirrors -------------------------------------------------------

interface RobotFact {
  name: string;
  form: string;
  anatomy: string[];
}

export const ROBOT_FACTS: Record<string, RobotFact> = {
  "unitree-g1": { name: "Unitree G1", form: "bipedal humanoid", anatomy: ["arm", "legs", "cameras"] },
  "unitree-r1": { name: "Unitree R1", form: "compact agile robot", anatomy: ["legs", "cameras"] },
  "1x-neo": { name: "1X NEO", form: "bipedal humanoid", anatomy: ["arm", "legs", "cameras"] },
  "unitree-go2": { name: "Unitree Go2", form: "quadruped", anatomy: ["legs", "cameras"] },
};

interface SkillFact {
  /** Robot anatomy this skill needs (mirrors skill_registry "requires"). */
  requires: string[];
  /** Replay pacing in ms — heavier steps take longer to "run". */
  weightMs: number;
  /** Chance the seeded run fails this step (only when structural checks pass). */
  failRate: number;
  /** Reason shown when the seeded run fails this step. */
  failNote: string;
}

const SKILL_FACTS: Record<string, SkillFact> = {
  "scene-creation": {
    requires: [], weightMs: 2200, failRate: 0.02,
    failNote: "scene build failed — a mesh import was missing its collision body",
  },
  "synthetic-data-generation": {
    requires: [], weightMs: 3200, failRate: 0.05,
    failNote: "data generation aborted — the domain-randomization budget was exhausted before the target demo count",
  },
  "policy-training-gr00t": {
    requires: ["arm"], weightMs: 5600, failRate: 0.1,
    failNote: "training diverged — the loss plateaued at 0.31 after 100 epochs instead of converging",
  },
  "policy-training-loco": {
    requires: ["legs"], weightMs: 5200, failRate: 0.1,
    failNote: "training diverged — the gait policy fell over past 0.8 m/s instead of converging",
  },
  "legged-manipulation": {
    requires: ["legs", "cameras"], weightMs: 4800, failRate: 0.09,
    failNote: "body-manipulation training stalled — the robot couldn't hold the payload stable while pushing",
  },
  "terrain-adaptation": {
    requires: ["legs"], weightMs: 4400, failRate: 0.09,
    failNote: "terrain training stalled — the recovery gait failed on the slippery tile set",
  },
  "perception-training": {
    requires: ["cameras"], weightMs: 3400, failRate: 0.06,
    failNote: "perception training stalled — mAP plateaued at 0.61 on the hardest classes",
  },
  "world-model-generation": {
    requires: ["cameras"], weightMs: 3000, failRate: 0.06,
    failNote: "world-model generation stalled — predicted physics drifted below the consistency bar",
  },
  "policy-validation": {
    requires: [], weightMs: 3600, failRate: 0.04,
    failNote: "validation failed — 42/50 scenarios passed, below the 90% acceptance threshold",
  },
  "motion-generation": {
    requires: ["arm"], weightMs: 2200, failRate: 0.03,
    failNote: "motion planning failed — no collision-free trajectory was found for 3 of the 12 grasps",
  },
  "policy-deployment": {
    requires: [], weightMs: 2400, failRate: 0.02,
    failNote: "deployment build failed — the ROS2 package didn't compile in the sandbox",
  },
};

const UNKNOWN_FACT: SkillFact = {
  requires: [], weightMs: 2800, failRate: 0.05,
  failNote: "step failed — the sandbox run reported an unexpected error",
};

/** Steps that build something the validation/deployment steps depend on. */
const TRAIN_IDS = new Set([
  "policy-training-gr00t",
  "policy-training-loco",
  "legged-manipulation",
  "terrain-adaptation",
  "perception-training",
]);

function factFor(skillId: string): SkillFact {
  return SKILL_FACTS[skillId] ?? UNKNOWN_FACT;
}

// --- deterministic PRNG (no Math.random anywhere in the plan) --------------

function fnv1a(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- plan types -------------------------------------------------------------

export type DryRunVerdict = "pass" | "fail";

export interface DryRunIssue {
  order: number;
  name: string;
  reason: string;
}

export interface DryRunStep {
  order: number;
  name: string;
  skillId: string;
  description: string;
  gpu: boolean;
  costUsd: number;
  /** Deterministic structural verdict (robot anatomy / step ordering). */
  structural: boolean;
  /** Reason a structural check failed (else undefined). */
  preflight?: string;
  /** Simulated replay pacing in ms — 0 when a structural check fails (the
   *  sim halts the moment that step is reached, nothing to replay). */
  durationMs: number;
  startMs: number;
  endMs: number;
  /** Lines replayed while the step runs (last one carries the verdict). */
  lines: string[];
  verdict: DryRunVerdict;
  /** Failure reason shown under the step once the run reaches it. */
  reason: string;
}

export interface DryRunPlan {
  robot: string;
  robotName: string;
  seed: number;
  estimatedMinutes: number;
  /** Whole-plan structural scan, shown before the replay starts. */
  issues: DryRunIssue[];
  steps: DryRunStep[];
  /** Total replay pacing in ms (all steps, no halting). */
  replayMs: number;
  /** Replay ms at which the run stops: end of the first failing step (or
   *  replayMs when every step passes). */
  haltMs: number;
  firstFailIndex: number; // -1 when the whole plan passes
}

// --- structural rules -------------------------------------------------------

function anatomyReason(
  step: { name: string; skill_id: string },
  robotFact: RobotFact,
  fact: SkillFact
): string | undefined {
  const missing = fact.requires.filter(r => !robotFact.anatomy.includes(r));
  if (missing.length === 0) return undefined;
  const parts = missing.length === 1 ? missing[0] : `${missing.slice(0, -1).join(", ")} or ${missing[missing.length - 1]}`;
  return `step '${step.name}' uses ${step.skill_id}, which needs ${parts} — the ${robotFact.name} (${robotFact.form}) has none. pick a robot with that anatomy or remove the step.`;
}

/** Ordering rules only make sense with the whole plan in view. */
function orderingReason(
  step: { name: string; skill_id: string },
  index: number,
  total: number,
  firstTrainIndex: number // -1 when the plan never trains anything
): string | undefined {
  if (step.skill_id === "policy-validation") {
    if (firstTrainIndex === -1 || firstTrainIndex >= index) {
      return "no trained policy to validate — this step runs before any training step. move a training step ahead of it.";
    }
    return undefined;
  }
  if (step.skill_id === "policy-deployment") {
    if (firstTrainIndex === -1 || firstTrainIndex >= index) {
      return "nothing to deploy — this step ships before any training step. train a policy first.";
    }
    if (index !== total - 1) {
      const after = total - index - 1;
      return `deployment is not the final step — ${after} step${after === 1 ? "" : "s"} after it would never reach the robot. move deployment last.`;
    }
    return undefined;
  }
  if (step.skill_id === "synthetic-data-generation" && firstTrainIndex !== -1 && firstTrainIndex < index) {
    return "stale data — this step generates training data after training already started. move it ahead of the training step.";
  }
  return undefined;
}

// --- the planner ------------------------------------------------------------

export function planDryRun(pipeline: Pipeline, robot: string, seed: number): DryRunPlan {
  const robotFact = ROBOT_FACTS[robot] ?? { name: robot, form: "robot", anatomy: [] };
  const subs = pipeline.subtasks;
  const firstTrainIndex = subs.findIndex(s => TRAIN_IDS.has(s.skill_id));

  // Deterministic per-step seeds: (seed, robot, skill, order).
  const rngFor = (skillId: string, order: number) =>
    mulberry32(fnv1a(`${seed}:${robot}:${skillId}:${order}`));

  let cursor = 0;
  const steps: DryRunStep[] = subs.map((st) => {
    const fact = factFor(st.skill_id);
    const rng = rngFor(st.skill_id, st.order);
    const anatomy = anatomyReason(st, robotFact, fact);
    const ordering = anatomy ? undefined : orderingReason(st, st.order - 1, subs.length, firstTrainIndex);
    const preflight = anatomy ?? ordering;

    let verdict: DryRunVerdict;
    let reason = "";
    let durationMs: number;
    if (preflight) {
      verdict = "fail";
      durationMs = 0;
      reason = `structural check: ${preflight}`;
    } else {
      // Seeded execution risk: ~0.85–1.15x pacing jitter around the skill
      // weight, then a fail coin flipped at the skill's metadata fail rate.
      const jitter = 0.85 + rng() * 0.3;
      durationMs = Math.max(200, Math.round(fact.weightMs * jitter));
      const failed = rng() < fact.failRate;
      verdict = failed ? "fail" : "pass";
      if (failed) reason = `${fact.failNote} — replay with a new scenario, or simplify the step.`;
    }

    const base = preflight
      ? [`${st.skill_id}.blocked() → ${preflight}`]
      : [
          `${st.skill_id}.init() → ${st.gpu_required ? "reserving GPU" : "cpu"} runtime`,
          `${st.skill_id}.run() → ${st.description}`,
          `${st.skill_id}.check() → reviewing output`,
        ];
    const lines = [...base];
    if (!preflight) lines.push(verdict === "pass" ? `✓ ${st.skill_id}.complete()` : `✗ ${st.skill_id}.complete()`);

    const step: DryRunStep = {
      order: st.order,
      name: st.name,
      skillId: st.skill_id,
      description: st.description,
      gpu: st.gpu_required,
      costUsd: st.estimated_cost_usd,
      structural: Boolean(preflight),
      preflight,
      durationMs,
      startMs: cursor,
      endMs: cursor + durationMs,
      lines,
      verdict,
      reason,
    };
    cursor += durationMs;
    return step;
  });

  const issues: DryRunIssue[] = steps
    .filter(s => s.structural)
    .map(s => ({ order: s.order, name: s.name, reason: s.preflight ?? "" }));

  const firstFailIndex = steps.findIndex(s => s.verdict === "fail");
  return {
    robot,
    robotName: robotFact.name,
    seed,
    estimatedMinutes: Math.max(1, Math.round(pipeline.estimated_time_minutes || 0)),
    issues,
    steps,
    replayMs: cursor,
    haltMs: firstFailIndex === -1 ? cursor : steps[firstFailIndex].endMs,
    firstFailIndex,
  };
}

// --- tiny display helpers ---------------------------------------------------

/** Compressed replay seconds, e.g. "4s" or "0.8s". */
export function fmtReplay(ms: number): string {
  const s = ms / 1000;
  return s >= 10 ? `${Math.round(s)}s` : `${s.toFixed(1)}s`;
}
