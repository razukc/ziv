// Adaptation layer: turns the diff between a composed pipeline and its seeded
// variation into per-step notes users can read ("why this skill still applies /
// was dropped"). Pure data + helpers — no React, no LLM: the reasons are
// derived deterministically from the two plans and the robot registry.
//
// Anatomy tables below mirror the backend (agent/robot_registry.py and
// agent/skill_registry.py "requires") so mock-mode and offline renders can
// explain drops without a network call. Keep them in sync when the registry
// changes.

import type { AdaptationEntry, AdaptationReport, DroppedEntry, Pipeline, Subtask } from "./types";

/** Robot slug -> anatomy the robot actually has. Mirror of robot_registry.py. */
const ROBOT_ANATOMY: Record<string, string[]> = {
  "unitree-g1": ["arm", "legs", "cameras"],
  "unitree-r1": ["legs", "cameras"],
  "1x-neo": ["arm", "legs", "cameras"],
  "unitree-go2": ["legs", "cameras"],
};

/** Skill id -> anatomy the skill requires. Mirror of skill_registry.py. */
const SKILL_REQUIRES: Record<string, string[]> = {
  "scene-creation": [],
  "synthetic-data-generation": [],
  "policy-training-gr00t": ["arm"],
  "policy-training-loco": ["legs"],
  "policy-validation": [],
  "policy-deployment": [],
  "motion-generation": ["arm"],
  "perception-training": ["cameras"],
  "world-model-generation": ["cameras"],
  "legged-manipulation": ["legs", "cameras"],
  "terrain-adaptation": ["legs"],
};

const ROBOT_LABELS: Record<string, string> = {
  "unitree-g1": "Unitree G1",
  "unitree-r1": "Unitree R1",
  "1x-neo": "1X NEO",
  "unitree-go2": "Unitree Go2",
};

export function robotLabel(robot: string): string {
  return ROBOT_LABELS[robot] || robot;
}

/** Same wording after normalizing case and whitespace. */
function sameWording(a: Subtask, b: Subtask): boolean {
  const norm = (s: string) => (s || "").trim().toLowerCase().replace(/\s+/g, " ");
  return norm(a.name) === norm(b.name) && norm(a.description) === norm(b.description);
}

/** Join missing anatomy for "has no …" reasons: "arm" / "legs or cameras". */
function missingPartsPhrase(missing: string[]): string {
  if (missing.length === 1) return missing[0];
  return `${missing.slice(0, -1).join(", ")} or ${missing[missing.length - 1]}`;
}

/**
 * Diff a seeded variation against its original plan. Every variation step is
 * tagged still-applies / reworded / new (matched to the original by skill id),
 * and every original step that didn't survive is reported with a reason:
 * robot-anatomy when the new robot physically can't use the skill, otherwise
 * "no longer part of the reworded task".
 */
export function diffAdaptation(original: Pipeline, variation: Pipeline): AdaptationReport {
  const matchedOriginals = new Set<number>(); // indexes into original.subtasks
  const steps: AdaptationEntry[] = [];

  for (const st of variation.subtasks) {
    const origIdx = original.subtasks.findIndex(
      (o, i) => o.skill_id === st.skill_id && !matchedOriginals.has(i)
    );
    if (origIdx === -1) {
      steps.push({
        order: st.order,
        name: st.name,
        skill_id: st.skill_id,
        badge: "new",
        note: "not in the original plan — added because the reworded task or robot calls for it.",
      });
      continue;
    }
    matchedOriginals.add(origIdx);
    const orig = original.subtasks[origIdx];
    steps.push({
      order: st.order,
      name: st.name,
      skill_id: st.skill_id,
      badge: sameWording(orig, st) ? "still-applies" : "reworded",
      note: sameWording(orig, st)
        ? "carried over unchanged — this part of the job still applies to the new plan."
        : "kept because it still applies — the wording was adapted for the new task.",
    });
  }

  const dropped: DroppedEntry[] = [];
  const variationAnatomy = new Set(ROBOT_ANATOMY[variation.robot] || []);
  original.subtasks.forEach((o, i) => {
    if (matchedOriginals.has(i)) return;
    const requires = SKILL_REQUIRES[o.skill_id] || [];
    const missing = requires.filter(part => !variationAnatomy.has(part));
    const reason = missing.length
      ? `dropped — ${robotLabel(variation.robot)} has no ${missingPartsPhrase(missing)}, and ${o.skill_id} needs it to work.`
      : "dropped — no longer part of the reworded task.";
    dropped.push({ order: o.order, name: o.name, skill_id: o.skill_id, reason });
  });

  return {
    fromRobot: original.robot,
    toRobot: variation.robot,
    steps,
    dropped,
  };
}

/** Quick counts for card headers ("3 kept · 1 added · 2 dropped"). */
export function adaptationCounts(report: AdaptationReport): {
  kept: number;
  added: number;
  dropped: number;
} {
  return {
    kept: report.steps.filter(s => s.badge !== "new").length,
    added: report.steps.filter(s => s.badge === "new").length,
    dropped: report.dropped.length,
  };
}

export type { AdaptationReport };
