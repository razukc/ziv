"""Robot capability profiles for the SkillForge backend.

Each registered robot declares the anatomy it actually has (``anatomy``:
arm / legs / cameras). Catalog skills declare the anatomy they require (see
``skill_registry.py``). Every LLM-composed pipeline — fresh or a seeded
variation — is checked against the *requested* robot's profile before it is
stored, so a plan can't silently ask an armless robot to train an arm policy.
The prompt is no longer the only thing keeping skill selection honest.
"""

from skill_registry import SKILL_CATALOG

# Canonical robot slugs the API accepts. The frontend picker offers the first
# three; unitree-go2 exists so quadruped-class robots are representable too.
# robot strings are NOT free-form any more: compose validates the slug against
# this registry instead of trusting whatever text arrives.
ROBOT_REGISTRY = {
    "unitree-g1": {"name": "Unitree G1", "form": "bipedal humanoid",
                   "anatomy": ("arm", "legs", "cameras")},
    "unitree-r1": {"name": "Unitree R1", "form": "compact agile robot",
                   "anatomy": ("legs", "cameras")},
    "1x-neo": {"name": "1X NEO", "form": "bipedal humanoid",
               "anatomy": ("arm", "legs", "cameras")},
    "unitree-go2": {"name": "Unitree Go2", "form": "quadruped",
                    "anatomy": ("legs", "cameras")},
}


def get_robot(robot):
    """Profile dict for a robot slug, or None when the slug isn't registered."""
    return ROBOT_REGISTRY.get(robot)


def known_robots():
    """Sorted robot slugs, for error messages and docs."""
    return sorted(ROBOT_REGISTRY)


def validate_pipeline_robot(pipeline: dict, robot: str):
    """Check a composed pipeline against the target robot's anatomy.

    Returns an error message when the pipeline can't run on this robot
    (or when the robot itself isn't registered), else None. Checks the
    requested robot slug — not the one the LLM echoed — so a seeded
    variation targeting a new robot is gated against that robot.
    """
    profile = get_robot(robot)
    if profile is None:
        return (f"robot '{robot}' is not in the robot registry "
                f"(known: {', '.join(known_robots())}). compose for one of these robots.")
    anatomy = set(profile["anatomy"])

    bad_steps = []
    for step in pipeline.get("subtasks", []):
        skill = SKILL_CATALOG.get(step.get("skill_id"))
        required = set(skill.get("requires", ())) if skill else set()
        missing = sorted(required - anatomy)
        if missing:
            bad_steps.append(
                f"step {step.get('order')} '{step.get('name')}' uses "
                f"{step.get('skill_id')}, which needs {_list_words(missing)}")
    if not bad_steps:
        return None

    missing_all = sorted({a for step in pipeline.get("subtasks", [])
                          for a in set(SKILL_CATALOG.get(step.get("skill_id"), {})
                                       .get("requires", ())) - anatomy})
    return (
        f"{profile['name']} ({profile['form']}) has no "
        f"{_list_words(missing_all)}, but the plan includes: "
        + "; ".join(bad_steps)
        + ". pick a robot with the right anatomy or adapt the steps to this robot's body."
    )


def _list_words(items):
    items = list(items)
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} or {items[-1]}"
