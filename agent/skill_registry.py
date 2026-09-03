"""
SkillForge - Skill Registry
Catalog of NVIDIA agent-ready skills available on Nebius.
"""

SKILL_CATALOG = {
    "scene-creation": {
        "id": "scene-creation",
        "name": "Omniverse Scene Creation",
        "product": "Omniverse / Isaac Sim",
        "description": "Create or import 3D scenes for robot simulation.",
        "tags": ["scene", "simulation", "environment"],
        "gpu_required": True,
        "estimated_cost_usd": 0.15,
    },
    "synthetic-data-generation": {
        "id": "synthetic-data-generation",
        "name": "Synthetic Data Factory",
        "product": "Cosmos / Isaac Sim",
        "description": "Generate physics-grounded synthetic training data.",
        "tags": ["data", "training", "cosmos"],
        "gpu_required": True,
        "estimated_cost_usd": 0.50,
    },
    "policy-training-gr00t": {
        "id": "policy-training-gr00t",
        "name": "GR00T N1 Policy Training",
        "product": "NVIDIA GR00T N1",
        "description": "Fine-tune GR00T N1 foundation model on custom task data.",
        "tags": ["training", "policy", "gr00t"],
        "gpu_required": True,
        "estimated_cost_usd": 2.00,
    },
    "policy-training-loco": {
        "id": "policy-training-loco",
        "name": "SONIC Locomotion Training",
        "product": "NVIDIA SONIC",
        "description": "Train whole-body locomotion policies for humanoid robots.",
        "tags": ["locomotion", "sonic", "walking"],
        "gpu_required": True,
        "estimated_cost_usd": 1.50,
    },
    "policy-validation": {
        "id": "policy-validation",
        "name": "Policy Validation Suite",
        "product": "Isaac Sim / RoboLab",
        "description": "Validate trained policies across simulation scenarios.",
        "tags": ["validation", "evaluation", "metrics"],
        "gpu_required": True,
        "estimated_cost_usd": 0.30,
    },
    "policy-deployment": {
        "id": "policy-deployment",
        "name": "Robot Deployment Package",
        "product": "Isaac Sim / ROS2",
        "description": "Package trained policy for real hardware deployment.",
        "tags": ["deployment", "ros2", "production"],
        "gpu_required": False,
        "estimated_cost_usd": 0.05,
    },
    "motion-generation": {
        "id": "motion-generation",
        "name": "Motion Planning",
        "product": "SONIC / cuMotion",
        "description": "Generate collision-free motion plans for manipulation.",
        "tags": ["motion", "planning", "trajectory"],
        "gpu_required": False,
        "estimated_cost_usd": 0.10,
    },
    "perception-training": {
        "id": "perception-training",
        "name": "Visual Perception Training",
        "product": "Tao Toolkit",
        "description": "Train object detection models for robot vision.",
        "tags": ["perception", "vision", "detection"],
        "gpu_required": True,
        "estimated_cost_usd": 0.40,
    },
    "world-model-generation": {
        "id": "world-model-generation",
        "name": "Cosmos World Model",
        "product": "NVIDIA Cosmos",
        "description": "Generate physics-grounded video predictions.",
        "tags": ["world-model", "cosmos", "prediction"],
        "gpu_required": True,
        "estimated_cost_usd": 0.25,
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
        "manipulation": ["scene-creation", "synthetic-data-generation", "policy-training-gr00t", "motion-generation", "policy-validation", "policy-deployment"],
        "locomotion": ["scene-creation", "synthetic-data-generation", "policy-training-loco", "policy-validation", "policy-deployment"],
        "perception": ["scene-creation", "synthetic-data-generation", "perception-training", "policy-validation"],
        "navigation": ["scene-creation", "synthetic-data-generation", "policy-training-loco", "policy-validation", "policy-deployment"],
    }
    ids = mapping.get(task_type, [])
    return [SKILL_CATALOG[sid] for sid in ids if sid in SKILL_CATALOG]
