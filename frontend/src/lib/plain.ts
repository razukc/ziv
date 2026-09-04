// Plain-language layer: turns robotics jargon into everyday sentences for
// people who are not robotics engineers. Pure data + helpers — no React —
// so the same glosses drive tooltips and the "in plain words" summary card.
//
// Resolution order for a step (see `plainStep`):
//   1. dictionary by skill id   (covers the full live skill catalog)
//   2. dictionary by step name  (covers LLM-style slug names)
//   3. keyword rules on name/description (rewrites arbitrary LLM phrasing)
//   4. the step's own description, then a humanized name as last resort

import type { Subtask } from "./types";

/** One plain sentence per known skill id: what the step actually accomplishes. */
export const PLAIN_SKILLS: Record<string, string> = {
  "scene-creation":
    "Set up a realistic 3D practice space — a virtual copy of the real world — so the robot can train safely instead of making mistakes on real objects.",
  "synthetic-data-generation":
    "Generate thousands of varied practice examples (like simulator training runs) so the robot learns from many different situations, not just one.",
  "policy-training-gr00t":
    "Teach the robot's AI brain — the GR00T N1 model — your exact task, using all the practice examples from the previous step.",
  "policy-training-loco":
    "Teach the robot how to balance and move its body using the practice examples, so walking feels natural instead of clumsy.",
  "motion-generation":
    "Plan the robot's movements in detail, so it reaches, grabs, and travels without bumping into or knocking over anything.",
  "policy-validation":
    "Test the trained robot across many different simulator scenarios to confirm it performs the task reliably every time.",
  "policy-deployment":
    "Package the finished skill into a standard software bundle that can be installed on the real robot.",
  "perception-training":
    "Teach the robot to recognize the objects and obstacles around it using its cameras, so it knows what it is looking at.",
  "world-model-generation":
    "Let the robot predict how objects in the scene will move or react, so it can prepare for what happens next instead of reacting late.",
  "legged-manipulation":
    "Teach the robot to handle objects without using hands — pushing them with its body, carrying them on its back or in a holder, and nudging them where they need to go.",
  "terrain-adaptation":
    "Harden the robot's walking so it stays sure-footed on rough, slippery, or uneven ground instead of stumbling.",
};

/**
 * Common LLM-style step *names* that don't match a skill id. These are the
 * slugs the model tends to invent (or that appear in stored/imported
 * pipelines) — mapped to the same everyday sentences as their catalog skill.
 */
const NAME_ALIASES: Record<string, string> = {
  "scene-creation": PLAIN_SKILLS["scene-creation"],
  "create-scene": PLAIN_SKILLS["scene-creation"],
  "environment-setup": PLAIN_SKILLS["scene-creation"],
  "synthetic-data": PLAIN_SKILLS["synthetic-data-generation"],
  "synthetic-data-generation": PLAIN_SKILLS["synthetic-data-generation"],
  "data-generation": PLAIN_SKILLS["synthetic-data-generation"],
  "demo-capture": PLAIN_SKILLS["synthetic-data-generation"],
  "gr00t-n1-finetune": PLAIN_SKILLS["policy-training-gr00t"],
  "gr00t-finetune": PLAIN_SKILLS["policy-training-gr00t"],
  "policy-training": PLAIN_SKILLS["policy-training-gr00t"],
  "policy-training-gr00t": PLAIN_SKILLS["policy-training-gr00t"],
  "sonic-loco-train": PLAIN_SKILLS["policy-training-loco"],
  "sonic-train": PLAIN_SKILLS["policy-training-loco"],
  "loco-train": PLAIN_SKILLS["policy-training-loco"],
  "policy-training-loco": PLAIN_SKILLS["policy-training-loco"],
  "motion-planning": PLAIN_SKILLS["motion-generation"],
  "motion-plan": PLAIN_SKILLS["motion-generation"],
  "trajectory-planning": PLAIN_SKILLS["motion-generation"],
  "motion-generation": PLAIN_SKILLS["motion-generation"],
  validation: PLAIN_SKILLS["policy-validation"],
  "policy-validation": PLAIN_SKILLS["policy-validation"],
  "policy-testing": PLAIN_SKILLS["policy-validation"],
  deployment: PLAIN_SKILLS["policy-deployment"],
  "policy-deployment": PLAIN_SKILLS["policy-deployment"],
  "ros2-package": PLAIN_SKILLS["policy-deployment"],
  "perception-train": PLAIN_SKILLS["perception-training"],
  "perception-training": PLAIN_SKILLS["perception-training"],
  "object-detection": PLAIN_SKILLS["perception-training"],
  "vision-training": PLAIN_SKILLS["perception-training"],
  "world-model": PLAIN_SKILLS["world-model-generation"],
  "world-model-generation": PLAIN_SKILLS["world-model-generation"],
  "legged-manipulation": PLAIN_SKILLS["legged-manipulation"],
  "legged-manip": PLAIN_SKILLS["legged-manipulation"],
  "body-manipulation": PLAIN_SKILLS["legged-manipulation"],
  "terrain-adaptation": PLAIN_SKILLS["terrain-adaptation"],
  "terrain-adapt": PLAIN_SKILLS["terrain-adaptation"],
  "rough-terrain-adaptation": PLAIN_SKILLS["terrain-adaptation"],
};

/**
 * Keyword rules for step names/descriptions the dictionary has never seen.
 * Ordered most-specific-first, so "sonic-loco-train" hits the locomotion rule
 * and never falls through to the generic "training" catch-all.
 */
const KEYWORD_RULES: Array<{ test: RegExp; text: string }> = [
  // Body-level object interaction must win over the generic arm-handling rule:
  // "push" / "carry" / "legged" are not dexterous grasping.
  {
    test: /legged|push|carry|payload|nudge|shov|nonprehensile/,
    text: PLAIN_SKILLS["legged-manipulation"],
  },
  // "rough" with a word boundary, so "through" doesn't trigger it.
  {
    test: /terrain|rough\b|slippery|uneven|muddy|rugged|gravel|slope/,
    text: PLAIN_SKILLS["terrain-adaptation"],
  },
  { test: /gr00t/, text: PLAIN_SKILLS["policy-training-gr00t"] },
  { test: /sonic|loco|walk|balanc|gait/, text: PLAIN_SKILLS["policy-training-loco"] },
  { test: /teleop|demonstrat|demo|data|synthetic/, text: PLAIN_SKILLS["synthetic-data-generation"] },
  { test: /perceiv|vision|visual|detect|recogn|segment|identif/, text: PLAIN_SKILLS["perception-training"] },
  {
    test: /grasp|pick|place|manipul|gripper|reach|hand/,
    text: "Practice the physical handling — reaching for objects, picking them up, and putting them where they belong.",
  },
  { test: /cosmos|world.?model|predict|physics/, text: PLAIN_SKILLS["world-model-generation"] },
  {
    test: /motion|trajector|avoid|collision|path/,
    text: PLAIN_SKILLS["motion-generation"],
  },
  { test: /valid|test|eval|benchmark|simulat/, text: PLAIN_SKILLS["policy-validation"] },
  { test: /scene|environment|3d/, text: PLAIN_SKILLS["scene-creation"] },
  { test: /deploy|package|ros2|export|docker|container/, text: PLAIN_SKILLS["policy-deployment"] },
  {
    test: /policy|train|learn|finetun|fine-?tun|teach/,
    text: "Teach the robot the new skill using the practice examples prepared for it.",
  },
];

function sentenceFromKeywords(name: string, description: string): string | undefined {
  for (const text of [name, description]) {
    const lower = (text || "").toLowerCase();
    if (!lower) continue;
    for (const rule of KEYWORD_RULES) {
      if (rule.test.test(lower)) return rule.text;
    }
  }
  return undefined;
}

/** Dictionary lookup by skill id (used for chip tooltips). */
export function skillGloss(id: string): string | undefined {
  return PLAIN_SKILLS[id];
}

/** "gr00t-n1-finetune" → "Gr00t n1 finetune" (last-resort fallback). */
export function humanize(name: string): string {
  const words = name
    .replace(/[-_]+/g, " ")
    .trim()
    .split(/\s+/);
  if (words.length === 0) return name;
  const first = words[0];
  return (
    first.charAt(0).toUpperCase() +
    first.slice(1) +
    (words.length > 1 ? ` ${words.slice(1).join(" ")}` : "")
  );
}

/**
 * One plain sentence explaining a single step. Resolves by skill id, then by
 * step name (aliases), then keyword rules over the name/description, then the
 * step's own description, and finally a humanized step name. This keeps even
 * pipelines with skills outside the catalog — live LLM steps, imported data —
 * readable to non-engineers.
 */
export function plainStep(st: Subtask): string {
  const byId = PLAIN_SKILLS[st.skill_id];
  if (byId) return byId;
  const byName = PLAIN_SKILLS[st.name] || NAME_ALIASES[st.name];
  if (byName) return byName;
  const ruled = sentenceFromKeywords(st.name, st.description);
  if (ruled) return ruled;
  const desc = (st.description || "").trim();
  if (desc) {
    const c = desc.charAt(0).toUpperCase() + desc.slice(1);
    return c.endsWith(".") ? c : `${c}.`;
  }
  return `${humanize(st.name)}.`;
}

const ROBOT_LABELS: Record<string, string> = {
  "unitree-g1": "Unitree G1",
  "unitree-r1": "Unitree R1",
  "1x-neo": "1X NEO",
};

/** What the robot ultimately learns to do, per pipeline task type. */
const TASK_TYPE_GOALS: Record<string, string> = {
  manipulation: "handle and move objects with its hands",
  locomotion: "move around safely — walking, balancing, and steering",
  navigation: "understand and move through indoor spaces without crashing into things",
  perception: "recognize and inspect the objects around it with its cameras",
  assembly: "put parts together in the right order, like a careful factory worker",
  inspection: "look closely at items and spot anything wrong with them",
  cleaning: "wipe, sort, and tidy up surfaces safely without knocking things over",
};

/**
 * A short plain-words overview for the analysis tab (mock mode). Mentions the
 * training arc in everyday terms instead of tool names, then the bottom line.
 */
export function plainOverview(taskType: string, costUsd: number, risk: string): string {
  const goal = TASK_TYPE_GOALS[taskType] || "carry out the task you described reliably";
  return (
    `Here's the plan in a nutshell: the robot learns to ${goal}. ` +
    `It first practices in a virtual 3D world where mistakes cost nothing, learns from ` +
    `thousands of generated examples, gets tested across dozens of simulated situations, ` +
    `and finishes as a ready-to-run software package for the real robot. ` +
    `Estimated cloud cost: $${costUsd.toFixed(2)}. Risk: ${risk}.`
  );
}

/** Human robot name for a robot code (fallback: the code itself). */
export function robotLabel(robot: string): string {
  return ROBOT_LABELS[robot] || robot;
}
