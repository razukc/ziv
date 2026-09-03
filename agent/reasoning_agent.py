import os
import json
from openai import OpenAI
from skill_registry import SKILL_CATALOG, list_all_skills


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

    def decompose_task(self, task_description, robot_type="unitree-g1", seed_pipeline=None):
        """
        Given a natural language task description, decompose it into
        subtasks and select the appropriate NVIDIA skills for each.

        When ``seed_pipeline`` is provided (an existing composed pipeline),
        the agent produces a VARIATION of it for the new task/robot: steps
        and skills that still apply are kept, the rest are adapted or
        dropped — instead of decomposing the task from scratch.
        """
        system_prompt = f"""You are SkillForge, an AI agent that composes robot skill pipelines.

You have access to these NVIDIA skills:
{self.skills_text}

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

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        content = response.choices[0].message.content.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        pipeline = json.loads(content)

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

    def explain_pipeline(self, pipeline):
        """Generate a human-readable explanation of the pipeline."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful robotics expert. Explain the following robot skill pipeline in plain English, highlighting key decisions and potential challenges. Be concise but thorough."},
                {"role": "user", "content": json.dumps(pipeline, indent=2)},
            ],
            temperature=0.5,
            max_tokens=1000,
        )
        return response.choices[0].message.content

    def suggest_improvements(self, pipeline):
        """Suggest improvements or alternatives for the pipeline."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a robotics optimization expert. Analyze this pipeline and suggest cost savings, reliability improvements, or alternative approaches. Be specific."},
                {"role": "user", "content": json.dumps(pipeline, indent=2)},
            ],
            temperature=0.4,
            max_tokens=800,
        )
        return response.choices[0].message.content


if __name__ == "__main__":
    agent = ReasoningAgent()
    result = agent.decompose_task("Pick up the red block from the table and place it on the blue platform")
    print(json.dumps(result, indent=2))
    print("\n--- Explanation ---")
    print(agent.explain_pipeline(result))
