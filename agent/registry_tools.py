"""Structured tool surface over the skill and robot registries.

The compose agent can query these tools during decomposition instead of
relying on catalog text baked into the prompt: exact skill details (cost,
GPU, required anatomy) and robot profiles come straight from
``skill_registry`` / ``robot_registry`` — the same registries the capability
gate validates against, so a plan grounded through these tools cannot drift
from what the gate will later accept.

The executor is intentionally pure and read-only: tools never write, so a
malformed call degrades to a JSON ``{"error": ...}`` the model can recover
from instead of a raised exception.
"""

import json

from robot_registry import get_robot, known_robots
from skill_registry import SKILL_CATALOG, list_all_skills

# --- OpenAI-style tool schemas (the SDK serializes these into the request) ---


def _skill_summary(s, brief=False):
    """Serializable view of a catalog skill (tuples -> lists).

    ``brief`` drops the long description/tags: list_skills returns brief rows
    (the catalog text in the prompt already carries descriptions) so the
    tool payload stays small and the model's output budget survives the
    round-trip; get_skill returns the full record on demand.
    """
    out = {
        "id": s["id"],
        "name": s["name"],
        "product": s["product"],
        "requires": list(s.get("requires", ())),
        "gpu_required": s["gpu_required"],
        "estimated_cost_usd": s["estimated_cost_usd"],
    }
    if not brief:
        out["description"] = s["description"]
        out["tags"] = s.get("tags", [])
    return out


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List every skill in the NVIDIA catalog: id, name, product, required robot anatomy (arm/legs/cameras), GPU need, and estimated cost. Use get_skill for a skill's full description.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill",
            "description": "Get the full catalog record for one skill by its exact id (e.g. 'motion-generation'). Use this to verify cost, GPU need, or required anatomy before choosing a skill.",
            "parameters": {
                "type": "object",
                "properties": {"skill_id": {"type": "string", "description": "Exact skill id from the catalog."}},
                "required": ["skill_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_robot",
            "description": "Get the capability profile of a robot by its id (e.g. 'unitree-go2'): name, form factor, and the anatomy it actually has (arm/legs/cameras).",
            "parameters": {
                "type": "object",
                "properties": {"robot_id": {"type": "string", "description": "Exact robot id."}},
                "required": ["robot_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_capability",
            "description": "Check whether a skill can run on a robot: does the robot's anatomy cover everything the skill requires? Use this BEFORE emitting a skill for a target robot so plans never ask an armless robot to train an arm policy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "Exact skill id from the catalog."},
                    "robot_id": {"type": "string", "description": "Exact robot id."},
                },
                "required": ["skill_id", "robot_id"],
                "additionalProperties": False,
            },
        },
    },
]


def execute_tool(name: str, args: dict):
    """Run one tool call against the registries; always returns JSON-able data."""
    try:
        if name == "list_skills":
            return {"skills": [_skill_summary(s, brief=True) for s in list_all_skills()]}
        if name == "get_skill":
            skill_id = str(args.get("skill_id", ""))
            skill = SKILL_CATALOG.get(skill_id)
            if skill is None:
                return {"error": f"unknown skill id '{skill_id}' — pick from the catalog ids only"}
            return _skill_summary(skill)
        if name == "get_robot":
            robot_id = str(args.get("robot_id", ""))
            profile = get_robot(robot_id)
            if profile is None:
                return {"error": f"unknown robot id '{robot_id}' — known: {', '.join(known_robots())}"}
            return {"id": robot_id, **profile, "anatomy": list(profile["anatomy"])}
        if name == "check_capability":
            skill_id = str(args.get("skill_id", ""))
            robot_id = str(args.get("robot_id", ""))
            skill = SKILL_CATALOG.get(skill_id)
            profile = get_robot(robot_id)
            if skill is None:
                return {"error": f"unknown skill id '{skill_id}' — pick from the catalog ids only"}
            if profile is None:
                return {"error": f"unknown robot id '{robot_id}' — known: {', '.join(known_robots())}"}
            required = list(skill.get("requires", ()))
            missing = sorted(set(required) - set(profile["anatomy"]))
            return {
                "skill_id": skill_id,
                "robot_id": robot_id,
                "skill_name": skill["name"],
                "robot_name": profile["name"],
                "requires": required,
                "missing": missing,
                "compatible": not missing,
                "note": (
                    f"{skill['name']} can run on {profile['name']}"
                    if not missing
                    else f"{skill['name']} needs {', '.join(missing)} — {profile['name']} has none; pick a different skill or robot"
                ),
            }
        return {"error": f"unknown tool '{name}'"}
    except Exception as e:  # never let a bad tool call kill the compose
        return {"error": f"tool '{name}' failed: {e}"}


def tool_call_label(name: str, args: dict) -> str:
    """Short human line for the reasoning stream, e.g.
    ``🔧 queried get_skill(motion-generation)``."""
    if name == "list_skills":
        return "🔧 queried the skill catalog"
    if name == "get_skill":
        return f"🔧 queried get_skill({args.get('skill_id', '?')})"
    if name == "get_robot":
        return f"🔧 queried get_robot({args.get('robot_id', '?')})"
    if name == "check_capability":
        return f"🔧 checked {args.get('skill_id', '?')} against {args.get('robot_id', '?')}"
    return f"🔧 tool {name}"


def dumps(result) -> str:
    """JSON-serialize a tool result for the tool message content."""
    return json.dumps(result)