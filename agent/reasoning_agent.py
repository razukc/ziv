import os
import json
import time
from openai import OpenAI

import registry_tools
from skill_registry import SKILL_CATALOG, list_all_skills


# The live model occasionally returns an empty payload or truncated JSON.
# Each compose retries the (stateless) prompt this many times with backoff.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 0.8  # seconds; attempt n sleeps base * n


class ReasoningAgent:
    """
    SkillForge Reasoning Agent
    Uses Nemotron on Nebius Token Factory to decompose robot tasks
    and select the right NVIDIA skills for each subtask.
    """

    def __init__(self):
        self.client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY"),
        )
        self.model = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
        self.skills = list_all_skills()
        self.skills_text = self._format_skills_for_prompt()

    def _format_skills_for_prompt(self):
        lines = []
        for s in self.skills:
            lines.append(f"- {s['id']}: {s['name']} ({s['product']})")
            lines.append(f"  {s['description']}")
            lines.append(f"  GPU: {'Yes' if s['gpu_required'] else 'No'}, ~${s['estimated_cost_usd']:.2f}")
            lines.append(f"  Tags: {', '.join(s['tags'])}")
        return "\n".join(lines)

    def decompose_task(self, task_description, robot_type="unitree-g1", seed_pipeline=None,
                       on_retry=None, on_tool=None, max_tool_rounds=12, tools_enabled=True):
        """
        Given a natural language task description, decompose it into
        subtasks and select the appropriate NVIDIA skills for each.

        When ``seed_pipeline`` is provided (an existing composed pipeline),
        the agent produces a VARIATION of it for the new task/robot: steps
        and skills that still apply are kept, the rest are adapted or
        dropped — instead of decomposing the task from scratch.

        ``on_retry`` (optional) is called as ``on_retry(attempt, error)``
        after each failed attempt that is retried (attempt is 1-based), so
        callers can surface that a transient blip happened and healed.

        ``on_tool`` (optional) is called as ``on_tool(name, args, result)``
        for every registry tool the model invokes, so callers can show the
        grounding work (the catalog is also embedded in the prompt, so
        providers that reject tool definitions degrade to prompt-only).

        ``tools_enabled=False`` runs the classic prompt-only path (no tool
        schemas sent) — used for A/B measurement of grounding vs memory.
        """
        system_prompt = f"""You are SkillForge, an AI agent that composes robot skill pipelines.

You have access to these NVIDIA skills:
{self.skills_text}

You can also query the skill and robot registries directly with tools:
list_skills, get_skill, get_robot, check_capability. The catalog above is
authoritative — never invent a skill id. Its rows already list every
skill's cost and GPU need, so do NOT call list_skills or get_skill to
re-read it — those are for facts the catalog row omits.

Tool rules — follow exactly:
1. Before including a skill, call check_capability(skill_id, robot_id)
   ONLY when you are unsure the target robot has the anatomy the skill
   needs — one call per doubtful skill, then stop.
2. Tool calls are serial (one per turn), so keep them minimal: every call
delays the pipeline. Never verify a skill you are not going to emit.
3. Once the skills you will emit are confirmed, STOP calling tools and
return the pipeline JSON immediately.

Your job: Given a task description and target robot, decompose the task
into ordered subtasks and select the best skill for each.

Return ONLY valid JSON with this structure:
{{
  "task": "original task description",
  "robot": "target robot",
  "task_type": "manipulation|locomotion|perception|navigation|assembly",
  "subtasks": [
    {{
      "order": 1,
      "name": "subtask name",
      "description": "what this subtask does",
      "skill_id": "skill-from-catalog",
      "parameters": {{}},
      "estimated_cost_usd": 0.00,
      "gpu_required": true
    }}
  ],
  "total_estimated_cost_usd": 0.00,
  "estimated_time_minutes": 0,
  "risk_assessment": "low|medium|high",
  "notes": "any important considerations"
}}

Rules:
- Select skills ONLY from the catalog above
- Order subtasks logically (scene before training, training before validation)
- Keep total cost reasonable (less than $5 for simple, less than $10 for complex)
- Estimate time based on GPU requirements
- Flag potential failure points
"""

        user_msg = f"Task: {task_description}\nRobot: {robot_type}"
        if seed_pipeline is not None:
            user_msg += (
                "\n\nAn existing plan is provided below. Produce a VARIATION of it that "
                "fits the new task and robot above."
                + json.dumps(seed_pipeline, indent=2)
                + "\n\nVariation rules: keep the steps and skills that still apply, adapt or "
                "drop the ones that don't, and word each step for the new task. The new "
                "task and robot take precedence over the existing plan. Return the full "
                "JSON structure with skills ONLY from the catalog above."
            )

        pipeline = self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            # Tool rounds inflate the context the model must answer over; a
            # bigger budget keeps it from exhausting output mid-JSON after a
            # registry lookup (observed live as empty content + finish=length).
            max_tokens=4000,
            parse=self._extract_pipeline_json,
            on_retry=on_retry,
            tools=registry_tools.TOOL_SCHEMAS if tools_enabled else None,
            execute_tool=registry_tools.execute_tool if tools_enabled else None,
            on_tool=on_tool,
            max_tool_rounds=max_tool_rounds,
        )

        # Validate skill IDs
        for subtask in pipeline["subtasks"]:
            if subtask["skill_id"] not in SKILL_CATALOG:
                raise ValueError(f"Invalid skill_id: {subtask['skill_id']}")

        # Recalculate costs from registry
        total_cost = sum(
            SKILL_CATALOG[s["skill_id"]]["estimated_cost_usd"]
            for s in pipeline["subtasks"]
        )
        pipeline["total_estimated_cost_usd"] = round(total_cost, 2)

        return pipeline

    def explain_pipeline(self, pipeline, on_retry=None):
        """Generate a human-readable explanation of the pipeline."""
        return self._complete(
            [
                {"role": "system", "content": "You are a helpful robotics expert. Explain the following robot skill pipeline in plain English, highlighting key decisions and potential challenges. Be concise but thorough."},
                {"role": "user", "content": json.dumps(pipeline, indent=2)},
            ],
            temperature=0.5,
            max_tokens=1000,
            on_retry=on_retry,
        )

    def suggest_improvements(self, pipeline, on_retry=None):
        """Suggest improvements or alternatives for the pipeline."""
        return self._complete(
            [
                {"role": "system", "content": "You are a robotics optimization expert. Analyze this pipeline and suggest cost savings, reliability improvements, or alternative approaches. Be specific."},
                {"role": "user", "content": json.dumps(pipeline, indent=2)},
            ],
            temperature=0.4,
            max_tokens=800,
            on_retry=on_retry,
        )

    def _complete(self, messages, *, temperature, max_tokens, parse=None, on_retry=None,
                  tools=None, execute_tool=None, max_tool_rounds=12, on_tool=None):
        """Chat round-trip with bounded retry against transient model failures.

        The live model occasionally returns an empty payload (``content=None``)
        or truncated JSON. Retrying the same stateless prompt is cheap and
        usually lands; after ``_MAX_ATTEMPTS`` failures the last error is
        raised so callers can surface a clean failure.

        ``on_retry`` (optional) is invoked as ``on_retry(attempt, error)``
        after each failed attempt that gets retried (attempt is 1-based:
        1 = the first call failed, a second call is being made).

        When ``tools`` and ``execute_tool`` are given, the call becomes a
        tool loop: if the model responds with ``tool_calls`` they are
        executed against the registries and fed back as tool messages, up to
        ``max_tool_rounds``, until the model returns content. Providers that
        reject tool definitions (HTTP 400/404/422 on the request) degrade
        transparently to the prompt-only path — the catalog stays in the
        prompt, so grounding degrades to today's behavior rather than
        failing the compose.
        """
        last_error = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                tool_messages = list(messages)
                degraded = False  # provider rejected tools -> prompt-only
                rounds = 0
                while True:
                    kwargs = dict(model=self.model, messages=tool_messages,
                                  temperature=temperature, max_tokens=max_tokens)
                    if tools is not None and not degraded:
                        kwargs["tools"] = tools
                    try:
                        response = self.client.chat.completions.create(**kwargs)
                    except Exception as e:
                        if tools is not None and not degraded and getattr(e, "status_code", None) in (400, 404, 422):
                            degraded = True  # retry this attempt prompt-only
                            continue
                        raise
                    message = response.choices[0].message
                    tool_calls = getattr(message, "tool_calls", None)
                    if tool_calls and execute_tool is not None:
                        rounds += 1
                        if rounds > max_tool_rounds:
                            raise ValueError(
                                f"agent requested tools {max_tool_rounds} times without producing a pipeline")
                        tool_messages.append(message)
                        for tc in tool_calls:
                            try:
                                args = json.loads(tc.function.arguments or "{}")
                            except json.JSONDecodeError:
                                args = {}
                            result = execute_tool(tc.function.name, args)
                            if on_tool is not None:
                                on_tool(tc.function.name, args, result)
                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": registry_tools.dumps(result),
                            })
                        continue
                    content = message.content
                    if not content or not content.strip():
                        raise ValueError("agent returned an empty response")
                    return parse(content) if parse else content
            except Exception as e:
                last_error = e
                if attempt < _MAX_ATTEMPTS - 1:
                    if on_retry is not None:
                        on_retry(attempt + 1, e)
                    time.sleep(_RETRY_BACKOFF_BASE * (attempt + 1))
        raise last_error

    @staticmethod
    def _extract_pipeline_json(content):
        """Strip markdown code fences if present, then parse the pipeline JSON."""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content)


if __name__ == "__main__":
    agent = ReasoningAgent()
    result = agent.decompose_task("Pick up the red block from the table and place it on the blue platform")
    print(json.dumps(result, indent=2))
    print("\n--- Explanation ---")
    print(agent.explain_pipeline(result))
