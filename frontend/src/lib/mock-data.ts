// Mock data for the backend-free demo mode.

import type { ExecutionLog, Subtask, ThinkingStep } from "./types";

export interface MockPipeline {
  subtasks: Subtask[];
  task_type: string;
  total: number;
  time: number;
  risk: string;
  notes: string;
  explanation: string;
  thinking: ThinkingStep[];
  logs: (task: string) => ExecutionLog[];
}

// Robot options

export const ROBOT_OPTIONS = [
  { value: "unitree-g1", label: "Unitree G1", icon: "\u{1F916}", desc: "Bipedal humanoid, 180cm", type: "Humanoid" },
  { value: "unitree-r1", label: "Unitree R1", icon: "\u{1F9BF}", desc: "Compact agile robot", type: "Compact" },
  { value: "1x-neo", label: "1X NEO", icon: "\u{1F9BE}", desc: "Humanoid for home use", type: "Humanoid" },
];

// Example task descriptions

export const EXAMPLE_TASKS = [
  "Pick up the red block and place it on the blue platform",
  "Sort packages by size on a conveyor belt",
  "Walk from the door to the table avoiding obstacles",
  "Wipe the kitchen counter clean",
];

// Robot-specific mock pipelines

export const MOCK_PIPELINES: Record<string, MockPipeline> = {
  "unitree-g1": {
    task_type: "manipulation",
    total: 3.10, time: 12, risk: "low",
    notes: "Standard pick-and-place pipeline for humanoid.",
    subtasks: [
      { order: 1, name: "scene-creation", description: "Build 3D environment in Isaac Sim", skill_id: "scene-creation", estimated_cost_usd: 0.15, gpu_required: true },
      { order: 2, name: "synthetic-data", description: "Generate 500 pick-place demos", skill_id: "synthetic-data-generation", estimated_cost_usd: 0.50, gpu_required: true },
      { order: 3, name: "gr00t-n1-finetune", description: "Fine-tune GR00T N1 on task data", skill_id: "policy-training-gr00t", estimated_cost_usd: 2.00, gpu_required: true },
      { order: 4, name: "motion-planning", description: "Compute collision-free trajectories", skill_id: "motion-generation", estimated_cost_usd: 0.10, gpu_required: false },
      { order: 5, name: "validation", description: "Test across 50 Isaac Sim scenarios", skill_id: "policy-validation", estimated_cost_usd: 0.30, gpu_required: true },
      { order: 6, name: "deployment", description: "Export ROS2 package (2.3MB)", skill_id: "policy-deployment", estimated_cost_usd: 0.05, gpu_required: false },
    ],
    explanation: "This pipeline uses NVIDIA GR00T N1 for manipulation. The G1 humanoid's dexterity makes it ideal for pick-and-place tasks.\n\nScene creation ($0.15) builds the simulation. Synthetic data ($0.50) generates training demos. GR00T N1 fine-tuning ($2.00) learns the task. Motion planning ($0.10) ensures collision-free paths. Validation ($0.30) confirms success. Deployment ($0.05) packages for hardware.\n\nTotal: $3.10. Risk is LOW.",
    thinking: [
      { content: "parsing task_description...", step: 1, total: 5, timestamp: 0 },
      { content: "task_type = classify(task) \u2192 manipulation", step: 2, total: 5, timestamp: 300 },
      { content: "skill_match = select(robot=G1, type=manipulation) \u2192 GR00T N1", step: 3, total: 5, timestamp: 500 },
      { content: "pipeline = nemotron.generate(subtasks, robot=unitree-g1)", step: 4, total: 5, timestamp: 800 },
      { content: "validate(pipeline) \u2713 cost=$3.10 < $5.00", step: 5, total: 5, timestamp: 1100 },
    ],
    logs: (task) => [
      { content: "scene-creation.init() \u2192 loading Isaac Sim", status: "running", step: 1, total: 6, skill_id: "scene-creation", timestamp: 1500 },
      { content: "scene-creation.run() \u2192 building environment", status: "running", step: 1, total: 6, skill_id: "scene-creation", timestamp: 1800 },
      { content: "scene-creation.complete() \u2713", status: "completed", step: 1, total: 6, skill_id: "scene-creation", timestamp: 2200 },
      { content: "synthetic-data.init() \u2192 loading Cosmos", status: "running", step: 2, total: 6, skill_id: "synthetic-data-generation", timestamp: 2500 },
      { content: "synthetic-data.generate() \u2192 500 pick-place demos", status: "running", step: 2, total: 6, skill_id: "synthetic-data-generation", timestamp: 2800 },
      { content: "synthetic-data.complete() \u2713", status: "completed", step: 2, total: 6, skill_id: "synthetic-data-generation", timestamp: 3200 },
      { content: "gr00t-n1.init() \u2192 loading foundation model weights", status: "running", step: 3, total: 6, skill_id: "policy-training-gr00t", timestamp: 3500 },
      { content: "gr00t-n1.finetune() \u2192 100 epochs on task data", status: "running", step: 3, total: 6, skill_id: "policy-training-gr00t", timestamp: 3800 },
      { content: "gr00t-n1.complete() \u2713 loss=0.023", status: "completed", step: 3, total: 6, skill_id: "policy-training-gr00t", timestamp: 4200 },
      { content: "motion-plan.init() \u2192 cuMotion solver", status: "running", step: 4, total: 6, skill_id: "motion-generation", timestamp: 4500 },
      { content: "motion-plan.solve() \u2192 12 trajectories computed", status: "running", step: 4, total: 6, skill_id: "motion-generation", timestamp: 4800 },
      { content: "motion-plan.complete() \u2713", status: "completed", step: 4, total: 6, skill_id: "motion-generation", timestamp: 5200 },
      { content: "validation.init() \u2192 Isaac Sim test scenarios", status: "running", step: 5, total: 6, skill_id: "policy-validation", timestamp: 5500 },
      { content: "validation.run() \u2192 50/50 scenarios passed", status: "running", step: 5, total: 6, skill_id: "policy-validation", timestamp: 5800 },
      { content: "validation.complete() \u2713 success_rate=100%", status: "completed", step: 5, total: 6, skill_id: "policy-validation", timestamp: 6200 },
      { content: "deployment.init() \u2192 ROS2 package builder", status: "running", step: 6, total: 6, skill_id: "policy-deployment", timestamp: 6500 },
      { content: "deployment.build() \u2192 compiling nodes", status: "running", step: 6, total: 6, skill_id: "policy-deployment", timestamp: 6800 },
      { content: "deployment.complete() \u2713 pkg_size=2.3MB", status: "completed", step: 6, total: 6, skill_id: "policy-deployment", timestamp: 7200 },
    ],
  },
  "unitree-r1": {
    task_type: "locomotion",
    total: 2.50, time: 9, risk: "low",
    notes: "Locomotion pipeline for compact agile robot.",
    subtasks: [
      { order: 1, name: "scene-creation", description: "Build navigation environment in Isaac Sim", skill_id: "scene-creation", estimated_cost_usd: 0.15, gpu_required: true },
      { order: 2, name: "synthetic-data", description: "Generate walking trajectory data", skill_id: "synthetic-data-generation", estimated_cost_usd: 0.50, gpu_required: true },
      { order: 3, name: "sonic-loco-train", description: "Train locomotion policy with SONIC", skill_id: "policy-training-loco", estimated_cost_usd: 1.50, gpu_required: true },
      { order: 4, name: "validation", description: "Test across 30 navigation scenarios", skill_id: "policy-validation", estimated_cost_usd: 0.30, gpu_required: true },
      { order: 5, name: "deployment", description: "Export ROS2 locomotion package", skill_id: "policy-deployment", estimated_cost_usd: 0.05, gpu_required: false },
    ],
    explanation: "This pipeline uses NVIDIA SONIC for locomotion. The R1's compact form factor is optimized for agile navigation.\n\nScene creation ($0.15) builds the terrain. Synthetic data ($0.50) generates walking trajectories. SONIC training ($1.50) learns whole-body locomotion. Validation ($0.30) tests across scenarios. Deployment ($0.05) packages for the R1 hardware.\n\nTotal: $2.50. Risk is LOW.",
    thinking: [
      { content: "parsing task_description...", step: 1, total: 5, timestamp: 0 },
      { content: "task_type = classify(task) \u2192 locomotion", step: 2, total: 5, timestamp: 300 },
      { content: "skill_match = select(robot=R1, type=locomotion) \u2192 SONIC", step: 3, total: 5, timestamp: 500 },
      { content: "pipeline = nemotron.generate(subtasks, robot=unitree-r1)", step: 4, total: 5, timestamp: 800 },
      { content: "validate(pipeline) \u2713 cost=$2.50 < $5.00", step: 5, total: 5, timestamp: 1100 },
    ],
    logs: (task) => [
      { content: "scene-creation.init() \u2192 loading Isaac Sim terrain", status: "running", step: 1, total: 5, skill_id: "scene-creation", timestamp: 1500 },
      { content: "scene-creation.run() \u2192 building navigation environment", status: "running", step: 1, total: 5, skill_id: "scene-creation", timestamp: 1800 },
      { content: "scene-creation.complete() \u2713", status: "completed", step: 1, total: 5, skill_id: "scene-creation", timestamp: 2200 },
      { content: "synthetic-data.init() \u2192 loading Cosmos locomotion", status: "running", step: 2, total: 5, skill_id: "synthetic-data-generation", timestamp: 2500 },
      { content: "synthetic-data.generate() \u2192 300 walking trajectories", status: "running", step: 2, total: 5, skill_id: "synthetic-data-generation", timestamp: 2800 },
      { content: "synthetic-data.complete() \u2713", status: "completed", step: 2, total: 5, skill_id: "synthetic-data-generation", timestamp: 3200 },
      { content: "sonic.init() \u2192 loading locomotion foundation model", status: "running", step: 3, total: 5, skill_id: "policy-training-loco", timestamp: 3500 },
      { content: "sonic.train() \u2192 80 epochs, whole-body control", status: "running", step: 3, total: 5, skill_id: "policy-training-loco", timestamp: 3800 },
      { content: "sonic.complete() \u2713 reward=0.94", status: "completed", step: 3, total: 5, skill_id: "policy-training-loco", timestamp: 4200 },
      { content: "validation.init() \u2192 Isaac Sim navigation tests", status: "running", step: 4, total: 5, skill_id: "policy-validation", timestamp: 4500 },
      { content: "validation.run() \u2192 30/30 scenarios passed", status: "running", step: 4, total: 5, skill_id: "policy-validation", timestamp: 4800 },
      { content: "validation.complete() \u2713 success_rate=100%", status: "completed", step: 4, total: 5, skill_id: "policy-validation", timestamp: 5200 },
      { content: "deployment.init() \u2192 ROS2 locomotion package", status: "running", step: 5, total: 5, skill_id: "policy-deployment", timestamp: 5500 },
      { content: "deployment.build() \u2192 compiling gait nodes", status: "running", step: 5, total: 5, skill_id: "policy-deployment", timestamp: 5800 },
      { content: "deployment.complete() \u2713 pkg_size=1.8MB", status: "completed", step: 5, total: 5, skill_id: "policy-deployment", timestamp: 6200 },
    ],
  },
  "1x-neo": {
    task_type: "navigation",
    total: 2.75, time: 10, risk: "medium",
    notes: "Home navigation pipeline for humanoid.",
    subtasks: [
      { order: 1, name: "scene-creation", description: "Build home environment in Isaac Sim", skill_id: "scene-creation", estimated_cost_usd: 0.15, gpu_required: true },
      { order: 2, name: "perception-train", description: "Train object detection for home objects", skill_id: "perception-training", estimated_cost_usd: 0.40, gpu_required: true },
      { order: 3, name: "sonic-loco-train", description: "Train navigation locomotion with SONIC", skill_id: "policy-training-loco", estimated_cost_usd: 1.50, gpu_required: true },
      { order: 4, name: "world-model", description: "Generate physics predictions with Cosmos", skill_id: "world-model-generation", estimated_cost_usd: 0.25, gpu_required: true },
      { order: 5, name: "validation", description: "Test across 40 home navigation scenarios", skill_id: "policy-validation", estimated_cost_usd: 0.30, gpu_required: true },
      { order: 6, name: "deployment", description: "Export ROS2 navigation package", skill_id: "policy-deployment", estimated_cost_usd: 0.05, gpu_required: false },
    ],
    explanation: "This pipeline combines perception and locomotion for home navigation. The NEO's humanoid form enables navigating human environments.\n\nScene creation ($0.15) builds the home. Perception training ($0.40) teaches object recognition. SONIC locomotion ($1.50) enables walking. Cosmos world model ($0.25) predicts physics. Validation ($0.30) tests navigation. Deployment ($0.05) packages for NEO hardware.\n\nTotal: $2.75. Risk is MEDIUM due to unstructured home environments.",
    thinking: [
      { content: "parsing task_description...", step: 1, total: 5, timestamp: 0 },
      { content: "task_type = classify(task) \u2192 navigation", step: 2, total: 5, timestamp: 300 },
      { content: "skill_match = select(robot=NEO, type=navigation) \u2192 SONIC + Perception", step: 3, total: 5, timestamp: 500 },
      { content: "pipeline = nemotron.generate(subtasks, robot=1x-neo)", step: 4, total: 5, timestamp: 800 },
      { content: "validate(pipeline) \u2713 cost=$2.75 < $5.00, risk=medium", step: 5, total: 5, timestamp: 1100 },
    ],
    logs: (task) => [
      { content: "scene-creation.init() \u2192 loading Isaac Sim home", status: "running", step: 1, total: 6, skill_id: "scene-creation", timestamp: 1500 },
      { content: "scene-creation.run() \u2192 building home environment", status: "running", step: 1, total: 6, skill_id: "scene-creation", timestamp: 1800 },
      { content: "scene-creation.complete() \u2713", status: "completed", step: 1, total: 6, skill_id: "scene-creation", timestamp: 2200 },
      { content: "perception.init() \u2192 loading Tao Toolkit", status: "running", step: 2, total: 6, skill_id: "perception-training", timestamp: 2500 },
      { content: "perception.train() \u2192 200 epochs, 15 home objects", status: "running", step: 2, total: 6, skill_id: "perception-training", timestamp: 2800 },
      { content: "perception.complete() \u2713 mAP=0.89", status: "completed", step: 2, total: 6, skill_id: "perception-training", timestamp: 3200 },
      { content: "sonic.init() \u2192 loading locomotion model", status: "running", step: 3, total: 6, skill_id: "policy-training-loco", timestamp: 3500 },
      { content: "sonic.train() \u2192 90 epochs, indoor terrain", status: "running", step: 3, total: 6, skill_id: "policy-training-loco", timestamp: 3800 },
      { content: "sonic.complete() \u2713 reward=0.91", status: "completed", step: 3, total: 6, skill_id: "policy-training-loco", timestamp: 4200 },
      { content: "cosmos.init() \u2192 loading world model", status: "running", step: 4, total: 6, skill_id: "world-model-generation", timestamp: 4500 },
      { content: "cosmos.predict() \u2192 50 physics predictions", status: "running", step: 4, total: 6, skill_id: "world-model-generation", timestamp: 4800 },
      { content: "cosmos.complete() \u2713 confidence=0.92", status: "completed", step: 4, total: 6, skill_id: "world-model-generation", timestamp: 5200 },
      { content: "validation.init() \u2192 Isaac Sim home navigation", status: "running", step: 5, total: 6, skill_id: "policy-validation", timestamp: 5500 },
      { content: "validation.run() \u2192 38/40 scenarios passed", status: "running", step: 5, total: 6, skill_id: "policy-validation", timestamp: 5800 },
      { content: "validation.complete() \u2713 success_rate=95%", status: "completed", step: 5, total: 6, skill_id: "policy-validation", timestamp: 6200 },
      { content: "deployment.init() \u2192 ROS2 navigation package", status: "running", step: 6, total: 6, skill_id: "policy-deployment", timestamp: 6500 },
      { content: "deployment.build() \u2192 compiling nav nodes", status: "running", step: 6, total: 6, skill_id: "policy-deployment", timestamp: 6800 },
      { content: "deployment.complete() \u2713 pkg_size=3.1MB", status: "completed", step: 6, total: 6, skill_id: "policy-deployment", timestamp: 7200 },
    ],
  },
};
