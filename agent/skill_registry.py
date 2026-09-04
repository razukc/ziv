"""
SkillForge - Skill Registry
Catalog of NVIDIA agent-ready skills available on Nebius.

Each skill declares the robot anatomy it requires (``requires``): "arm",
"legs", or "cameras". Skills with no requirement (scene creation, data
synthesis, validation, packaging) work for any robot body. The compose path
checks every LLM-generated pipeline against the target robot's profile (see
robot_registry.py), so a plan can't ask an armless robot to train an arm
policy.
"""

SKILL_CATALOG = {
    "scene-creation": {
        "id": "scene-creation",
        "name": "Omniverse Scene Creation",
        "product": "Omniverse / Isaac Sim",
        "description": "Create or import 3D scenes for robot simulation.",
        "tags": ["scene", "simulation", "environment"],
        "requires": (),  # simulation only — no robot body involved
        "gpu_required": True,
        "estimated_cost_usd": 0.15,
    },
    "synthetic-data-generation": {
        "id": "synthetic-data-generation",
        "name": "Synthetic Data Factory",
        "product": "Cosmos / Isaac Sim",
        "description": "Generate physics-grounded synthetic training data.",
        "tags": ["data", "training", "cosmos"],
        "requires": (),
        "gpu_required": True,
        "estimated_cost_usd": 0.50,
    },
    "policy-training-gr00t": {
        "id": "policy-training-gr00t",
        "name": "GR00T N1 Policy Training",
        "product": "NVIDIA GR00T N1",
        "description": "Fine-tune GR00T N1 foundation model on custom task data.",
        "tags": ["training", "policy", "gr00t"],
        "requires": ("arm",),  # dexterous manipulation policy
        "gpu_required": True,
        "estimated_cost_usd": 2.00,
    },
    "policy-training-loco": {
        "id": "policy-training-loco",
        "name": "SONIC Locomotion Training",
        "product": "NVIDIA SONIC",
        "description": "Train whole-body locomotion policies for humanoid robots.",
        "tags": ["locomotion", "sonic", "walking"],
        "requires": ("legs",),
        "gpu_required": True,
        "estimated_cost_usd": 1.50,
    },
    "policy-validation": {
        "id": "policy-validation",
        "name": "Policy Validation Suite",
        "product": "Isaac Sim / RoboLab",
        "description": "Validate trained policies across simulation scenarios.",
        "tags": ["validation", "evaluation", "metrics"],
        "requires": (),  # simulation scenarios — validates whatever was trained
        "gpu_required": True,
        "estimated_cost_usd": 0.30,
    },
    "policy-deployment": {
        "id": "policy-deployment",
        "name": "Robot Deployment Package",
        "product": "Isaac Sim / ROS2",
        "description": "Package trained policy for real hardware deployment.",
        "tags": ["deployment", "ros2", "production"],
        "requires": (),
        "gpu_required": False,
        "estimated_cost_usd": 0.05,
    },
    "motion-generation": {
        "id": "motion-generation",
        "name": "Motion Planning",
        "product": "SONIC / cuMotion",
        "description": "Generate collision-free motion plans for manipulation.",
        "tags": ["motion", "planning", "trajectory"],
        "requires": ("arm",),  # arm trajectories for manipulation
        "gpu_required": False,
        "estimated_cost_usd": 0.10,
    },
    "perception-training": {
        "id": "perception-training",
        "name": "Visual Perception Training",
        "product": "Tao Toolkit",
        "description": "Train object detection models for robot vision.",
        "tags": ["perception", "vision", "detection"],
        "requires": ("cameras",),
        "gpu_required": True,
        "estimated_cost_usd": 0.40,
    },
    "world-model-generation": {
        "id": "world-model-generation",
        "name": "Cosmos World Model",
        "product": "NVIDIA Cosmos",
        "description": "Generate physics-grounded video predictions.",
        "tags": ["world-model", "cosmos", "prediction"],
        "requires": ("cameras",),  # predicts scene dynamics from video
        "gpu_required": True,
        "estimated_cost_usd": 0.25,
    },
    # Quadruped-class coverage: body-manipulation and terrain robustness for
    # robots that have legs but no dexterous arm (Unitree Go2, R1). Before
    # these existed, armless robots could only perceive, walk, and deploy —
    # no way to interact with objects or survive rough ground.
    "legged-manipulation": {
        "id": "legged-manipulation",
        "name": "Legged Manipulation",
        "product": "Isaac Lab / Isaac Sim",
        "description": "Train whole-body manipulation without an arm: push, carry, and reposition objects with the body and legs.",
        "tags": ["manipulation", "legged", "payload", "nonprehensile"],
        "requires": ("legs", "cameras"),  # body interaction + seeing the object
        "gpu_required": True,
        "estimated_cost_usd": 1.20,
    },
    "terrain-adaptation": {
        "id": "terrain-adaptation",
        "name": "Terrain Adaptation Training",
        "product": "NVIDIA SONIC / Isaac Lab",
        "description": "Train gaits and recovery that adapt to rough, slippery, or uneven terrain.",
        "tags": ["locomotion", "terrain", "rough-terrain", "robustness"],
        "requires": ("legs",),
        "gpu_required": True,
        "estimated_cost_usd": 1.00,
    },
}

def get_skill(skill_id):
    return SKILL_CATALOG.get(skill_id)

def search_skills(query):
    q = query.lower()
    return [s for s in SKILL_CATALOG.values()
            if q in s["name"].lower() or q in s["description"].lower()
            or any(q in t for t in s["tags"])]

def list_all_skills():
    return list(SKILL_CATALOG.values())

def get_skills_for_task_type(task_type):
    mapping = {
        "manipulation": ["scene-creation", "synthetic-data-generation", "policy-training-gr00t", "legged-manipulation", "motion-generation", "policy-validation", "policy-deployment"],
        "locomotion": ["scene-creation", "synthetic-data-generation", "policy-training-loco", "terrain-adaptation", "policy-validation", "policy-deployment"],
        "perception": ["scene-creation", "synthetic-data-generation", "perception-training", "policy-validation"],
        "navigation": ["scene-creation", "synthetic-data-generation", "policy-training-loco", "terrain-adaptation", "policy-validation", "policy-deployment"],
    }
    ids = mapping.get(task_type, [])
    return [SKILL_CATALOG[sid] for sid in ids if sid in SKILL_CATALOG]
