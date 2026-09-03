# Devpost Submission — SkillForge

Copy-paste the sections below into your Devpost project page.

---

## Project Name

SkillForge

## Tagline

Natural language to robot skill pipelines — powered by NVIDIA Nemotron on Nebius

## Short Description (one-liner)

SkillForge uses NVIDIA Nemotron to decompose plain-English robot tasks into costed, ordered pipelines of NVIDIA skills (Omniverse, GR00T N1, SONIC, Cosmos) — with ROS2 package export.

---

## Description (paste into "Description" field)

### The Problem

Building autonomous robot behaviors requires deep expertise across simulation, data generation, model training, validation, and deployment. Each step uses different NVIDIA tools (Omniverse, GR00T N1, SONIC, Cosmos), and knowing which to use, in what order, and at what cost is a barrier for robotics teams and researchers.

### Our Solution

SkillForge is an AI agent that takes a natural language task description — "Pick up the red block and place it on the blue platform" — and instantly generates a complete, ordered pipeline of NVIDIA skills. It uses Nemotron 30B on Nebius Token Factory to:

1. **Decompose** the task into logical subtasks
2. **Select** the best NVIDIA skill for each step from a catalog of 9 agent-ready tools
3. **Estimate** cost, time, and risk for the full pipeline
4. **Explain** its reasoning in plain English
5. **Export** as a buildable ROS2 package

### Why It Matters

- **Accessibility**: Non-experts can plan robot workflows without knowing every NVIDIA tool
- **Cost awareness**: Every pipeline shows per-step costs — critical when working with limited GPU credits
- **Speed**: What takes hours of research happens in seconds
- **Composability**: Pipelines are structured JSON — ready for execution, modification, or integration
- **Exportable**: Generated ROS2 packages are ready for colcon build and real robot deployment

---

## Key Technologies Used

- **NVIDIA Nemotron 3 Nano 30B-A3B** — Task decomposition and skill selection
- **Nebius Token Factory** — Inference backend for Nemotron
- **NVIDIA Omniverse / Isaac Sim** — Scene creation and simulation
- **NVIDIA GR00T N1** — Foundation model for robot manipulation
- **NVIDIA SONIC** — Whole-body locomotion training
- **NVIDIA Cosmos** — Synthetic data and world model generation
- **FastAPI** — Python backend with SSE streaming
- **Next.js 15 + React 19** — Frontend interface
- **TypeScript** — End-to-end type safety
- **ROS2 Humble** — Generated package target

---

## How We Built It

### Architecture

```
User Input → Frontend (Next.js) → API (FastAPI) → Nemotron 30B (Token Factory)
                                    ↓
                              Skill Catalog (9 NVIDIA skills)
                                    ↓
                              Pipeline JSON + ROS2 Package
```

### Design Decisions

1. **Static skill catalog over dynamic tool use**: We maintain a fixed registry of 9 NVIDIA skills with metadata (cost, GPU requirement, tags). This prevents LLM hallucination of non-existent tools and gives users transparent cost estimates.

2. **Nemotron 30B for structured output**: We chose Nemotron because it's instruction-tuned, fast on Token Factory, and excellent at producing the structured JSON that pipeline decomposition requires.

3. **Cost-first design**: Every skill has a per-use cost estimate. The agent is instructed to keep total pipeline costs under $5 for simple tasks and under $10 for complex ones — essential for working within hackathon credit budgets.

4. **Decompose-then-review**: By generating the full pipeline before execution, users can review, modify, or reject the plan before spending any GPU credits.

5. **Robot-specific pipelines**: Different robots (Unitree G1, R1, 1X NEO) produce different skill chains — manipulation for humanoids, locomotion for compact robots, navigation for home use.

6. **ROS2 package generation**: Pipelines export as buildable ROS2 packages with package.xml, CMakeLists.txt, launch files, and full dependency tracking.

---

## Accomplishments We're Proud Of

- **Working end-to-end**: Natural language → structured pipeline with real NVIDIA skill mappings
- **Cost transparency**: Every pipeline shows per-step and total cost estimates
- **Multi-robot support**: 3 robots with distinct pipelines — Unitree G1 (manipulation), Unitree R1 (locomotion), 1X NEO (navigation)
- **AI explanation**: The agent explains its reasoning in plain English, not just JSON
- **9-skill catalog**: Covers the full robot development lifecycle (scene → data → train → validate → deploy)
- **ROS2 export**: Generate buildable ROS2 packages with package.xml, CMakeLists, launch files
- **Pipeline validation**: Automated checks for XML, cmake, Python, and JSON syntax
- **Pipeline history**: Compare multiple pipelines side-by-side
- **Skill browser**: Explore the 9 NVIDIA skills with metadata, costs, and tags
- **Streaming SSE**: Real-time thinking process and execution logs during composition
- **Responsive design**: Works on desktop, tablet, and mobile
- **Error handling**: Validation, timeouts, rate limits, retry logic
- **Apache 2.0 license**: Enterprise-friendly with patent grant

---

## What We Learned

- **Structured output matters**: Getting reliable JSON from an LLM requires careful prompt engineering. We extract JSON from markdown code blocks and validate against the skill catalog.
- **Cost estimation is valuable**: Adding per-skill costs transforms an abstract pipeline into an actionable budget. Users immediately understand what they're spending.
- **Skill catalog design**: Mapping real NVIDIA products to abstract skill categories required deep familiarity with the NVIDIA robotics ecosystem.
- **Token Factory speed**: Nemotron on Token Factory is fast enough for interactive use — pipelines compose in under 10 seconds.
- **ROS2 package structure**: Generating valid ROS2 packages requires careful attention to package.xml schema, CMakeLists syntax, and launch file conventions.
- **SSE streaming**: Server-Sent Events provide a clean way to stream AI thinking process and execution logs to the frontend.

---

## What's Next for SkillForge

1. **Isaac Sim integration** — Execute generated pipelines directly in simulation
2. **Expanded skill catalog** — Add Isaac Lab, cuRobo, Isaac ROS, and more NVIDIA tools
3. **Pipeline editor** — Drag-and-drop UI to modify generated pipelines before execution
4. **Multi-robot orchestration** — Compose pipelines for teams of robots working together
5. **Real hardware deployment** — Connect to actual robots via ROS2 for end-to-end execution
6. **Pipeline versioning** — Save, compare, and iterate on pipeline designs over time
7. **Cost optimization mode** — Agent automatically suggests cheaper skill alternatives

---

## Devpost-Specific Answers

### What hackathon track are you in?
Physical AI Track

### What does your project do?
SkillForge turns plain-English robot task descriptions into complete, costed skill pipelines using NVIDIA's robotics ecosystem. It uses Nemotron on Nebius Token Factory to decompose tasks and select the right NVIDIA skills for each step. Pipelines export as buildable ROS2 packages.

### What makes your project unique?
It's the first tool that bridges natural language task descriptions to structured, costed NVIDIA skill pipelines with real ROS2 export. Unlike existing tools that focus on single capabilities (just training, just simulation), SkillForge covers the full lifecycle — from scene creation to deployment — in a single pipeline that's ready for real robots.

### What challenges did you face?
1. Extracting valid JSON from LLM responses (handling markdown code blocks, invalid skill IDs)
2. Designing a skill catalog that accurately maps to real NVIDIA products
3. Balancing pipeline completeness with cost constraints
4. Making the agent reliably order subtasks correctly (scene before training, training before validation)
5. Generating valid ROS2 packages (package.xml schema, CMakeLists syntax, launch file conventions)
6. Implementing real-time SSE streaming for the AI thinking process
7. Building robot-specific pipelines that reflect each robot's capabilities

### What technologies did you use?
NVIDIA Nemotron 30B, Nebius Token Factory, Omniverse, GR00T N1, SONIC, Cosmos, Isaac Sim, FastAPI, Server-Sent Events, Next.js 15, React 19, TypeScript, Python, ROS2 Humble, Apache 2.0

---

## License

Apache License 2.0 — see LICENSE file for details.

Generated ROS2 packages reference NVIDIA tools which have their own licenses. See https://developer.nvidia.com/licenses

---

## Screenshots to Capture

After running the app, take these screenshots for Devpost:

1. **Landing page** — Clean state with robot cards, task input, and suggestion chips
2. **Processing view** — Thinking steps streaming in, progress bar, execution logs
3. **Pipeline results** — Stats, timeline, tabs (analysis/reasoning/logs/json)
4. **Pipeline history** — Multiple composed pipelines with comparison view
5. **Skill browser** — Slide-out panel showing the 9 NVIDIA skills
6. **ROS2 export** — Generated package files with expandable previews
7. **Mobile view** — Responsive layout on phone-sized screen

Save them to `docs/` folder as:
- `docs/screenshot-landing.png`
- `docs/screenshot-processing.png`
- `docs/screenshot-results.png`
- `docs/screenshot-history.png`
- `docs/screenshot-skills.png`
- `docs/screenshot-export.png`
- `docs/screenshot-mobile.png`
