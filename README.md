# ⚙️ SkillForge

**Natural language in. NVIDIA robot skill pipelines out.**

> Nebius Global AI Hackathon 2026 · Physical AI Track

---

## Features

- **Natural language input** — Describe robot tasks in plain English
- **11 NVIDIA skills** — Scene creation, synthetic data, GR00T N1, SONIC, Cosmos, perception, motion planning, validation, deployment, legged manipulation, terrain adaptation
- **Robot profiles + capability gate** — Unitree G1 (manipulation), Unitree R1 (locomotion), 1X NEO (navigation), and Go2-class quadrupeds; skills declare the anatomy they need (arm/legs/cameras) and every compose is validated against the robot's body instead of trusting the model
- **Cost estimation** — Per-step and total pipeline costs
- **AI reasoning** — Streaming thinking process shows how Nemotron decomposes tasks
- **Registry-grounded compose** — fresh decomposes can query the skill/robot registries as structured tools (list_skills, get_skill, get_robot, check_capability) to verify costs, GPU needs, and anatomy before choosing skills — lookups show up as 🔧 lines in the reasoning stream and every compose reports how many tool calls grounded it. Seeded variations skip the tools (measured: they never trip the capability gate either way, and prompt-only is ~3× faster)
- **ROS2 export** — Generate buildable packages with package.xml, CMakeLists, launch files
- **Package validation** — Automated checks for XML, cmake, Python, and JSON syntax
- **Pipeline editing** — Reorder, swap, or remove steps and re-export without an LLM call
- **Create variation** — Reword the task or switch robots and compose a NEW pipeline adapted from the current one
- **Pipeline history** — Composed pipelines persist across reloads (localStorage for mock, Redis ids for live); reopen any one to tweak and re-export, or compare side-by-side — live cards show how long their compose took (⏱ 11s · retried 1×)
- **Skill browser** — Explore the 11 NVIDIA skills with metadata
- **Mock mode** — Full demo without backend (switch in the compose box)
- **Responsive design** — Works on desktop, tablet, and mobile
- **Error handling** — Validation, timeouts, rate limits, retry logic
- **Auto-retry awareness** — healed LLM blips are counted per session, and once the model has auto-retried 3+ times the UI suggests mock mode or a simpler task
- **Latency visibility** — live composes tick a running elapsed while processing and finish with a "compose took Xs (auto-retried N×)" line plus a per-phase breakdown (decompose · explain · logs), so slow LLM round-trips read as slow, not stuck, and you can see which step dominates
- **Slow-compose warning** — a compose that beats the session's moving time baseline (2× the recent median) gets a warn note suggesting a retry or a simpler task
- **Simulation dry-run** — "▶ sim dry-run" on any pipeline replays it step-by-step with real pacing and seeded pass/fail against skill metadata: structural checks (anatomy fit, step ordering) always fail the same way, same plan + same seed = same outcome, and "🎲 new scenario" rerolls execution risk — the honest scaffold a real simulation engine can later plug into. Verdicts persist: history cards show the last result (🧪 pass · 14s · seed) and reopening a pipeline renders it instantly without re-running

---

## What It Does

SkillForge is an AI agent that turns plain-English robot task descriptions into complete, costed skill pipelines using NVIDIA's ecosystem. Tell it *"Pick up the red block and place it on the blue platform"* and it decomposes the task, selects the right NVIDIA skills (Omniverse, GR00T N1, SONIC, Cosmos…), and returns an ordered pipeline with cost estimates, time projections, and risk assessments.

**One sentence. Full pipeline. Real costs.**

---

## Demo

![SkillForge UI — Pipeline Result](docs/screenshot-pipeline.png)
<!-- Replace with actual screenshot after running the app -->

**Try it live:** Describe a task, pick a robot, hit Compose.

---

## How It Works

```
┌──────────────────────────────────────────────────────┐
│  User enters: "Sort packages by size on a conveyor"  │
│  Robot: Unitree G1                                   │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  Nemotron 30B (Nebius Token Factory)                 │
│  • Parses task intent & robot constraints            │
│  • Decomposes into ordered subtasks                  │
│  • Selects best NVIDIA skill for each step           │
│  • Estimates cost, time, and risk                    │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  Pipeline Output                                     │
│  1. Scene Creation (Omniverse)        $0.15         │
│  2. Synthetic Data Generation (Cosmos) $0.50        │
│  3. Policy Training (GR00T N1)         $2.00        │
│  4. Policy Validation (Isaac Sim)      $0.30        │
│  5. Deployment Package (ROS2)          $0.05        │
│                                          ─────────   │
│  Total estimated:                       $3.00       │
└──────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI Model** | NVIDIA Nemotron 3 Nano 30B-A3B |
| **Inference** | Nebius Token Factory |
| **Skill Catalog** | 11 NVIDIA agent-ready skills (Omniverse, GR00T N1, SONIC, Cosmos, Tao, cuMotion, Isaac Lab, ROS2) |
| **Backend** | Python · FastAPI · Uvicorn |
| **Frontend** | Next.js 15 · React 19 · TypeScript |
| **Cost Tracking** | Built-in per-skill cost estimation |

---

## The 11 NVIDIA Skills

| Skill | Product | GPU | Est. Cost | Description |
|-------|---------|-----|-----------|-------------|
| `scene-creation` | Omniverse / Isaac Sim | ✅ | $0.15 | Create or import 3D scenes for simulation |
| `synthetic-data-generation` | Cosmos / Isaac Sim | ✅ | $0.50 | Generate physics-grounded training data |
| `policy-training-gr00t` | GR00T N1 | ✅ | $2.00 | Fine-tune GR00T N1 foundation model |
| `policy-training-loco` | SONIC | ✅ | $1.50 | Train whole-body locomotion policies |
| `policy-validation` | Isaac Sim / RoboLab | ✅ | $0.30 | Validate trained policies in simulation |
| `policy-deployment` | Isaac Sim / ROS2 | ❌ | $0.05 | Package policy for real hardware |
| `motion-generation` | SONIC / cuMotion | ❌ | $0.10 | Collision-free motion planning |
| `perception-training` | Tao Toolkit | ✅ | $0.40 | Train object detection for robot vision |
| `world-model-generation` | Cosmos | ✅ | $0.25 | Physics-grounded video predictions |
| `legged-manipulation` | Isaac Lab / Isaac Sim | ✅ | $1.20 | Push, carry, and reposition objects with the body and legs — no arm needed (Go2-class robots) |
| `terrain-adaptation` | SONIC / Isaac Lab | ✅ | $1.00 | Gaits and recovery that adapt to rough, slippery, or uneven ground |

---

## Example Pipelines

### 🤖 "Pick up the red block and place it on the blue platform"
**Robot:** Unitree G1 · **Type:** Manipulation · **Risk:** Low

| # | Step | Skill | Cost |
|---|------|-------|------|
| 1 | Create table scene | `scene-creation` | $0.15 |
| 2 | Generate pick-place training data | `synthetic-data-generation` | $0.50 |
| 3 | Train GR00T N1 policy | `policy-training-gr00t` | $2.00 |
| 4 | Generate motion plan | `motion-generation` | $0.10 |
| 5 | Validate in simulation | `policy-validation` | $0.30 |
| 6 | Package for deployment | `policy-deployment` | $0.05 |
| | **Total** | | **$3.10** |

### 🚶 "Walk from the door to the table avoiding obstacles"
**Robot:** Unitree G1 · **Type:** Locomotion · **Risk:** Medium

| # | Step | Skill | Cost |
|---|------|-------|------|
| 1 | Create room environment | `scene-creation` | $0.15 |
| 2 | Generate navigation data | `synthetic-data-generation` | $0.50 |
| 3 | Train SONIC locomotion | `policy-training-loco` | $1.50 |
| 4 | Validate navigation | `policy-validation` | $0.30 |
| 5 | Deploy to robot | `policy-deployment` | $0.05 |
| | **Total** | | **$2.50** |

### 👁️ "Identify and sort packages by barcode on a conveyor"
**Robot:** 1X NEO · **Type:** Perception + Manipulation · **Risk:** High

| # | Step | Skill | Cost |
|---|------|-------|------|
| 1 | Create conveyor scene | `scene-creation` | $0.15 |
| 2 | Generate barcode detection data | `synthetic-data-generation` | $0.50 |
| 3 | Train perception model | `perception-training` | $0.40 |
| 4 | Generate world predictions | `world-model-generation` | $0.25 |
| 5 | Train manipulation policy | `policy-training-gr00t` | $2.00 |
| 6 | Validate end-to-end | `policy-validation` | $0.30 |
| 7 | Deploy | `policy-deployment` | $0.05 |
| | **Total** | | **$3.65** |

---

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- A [Nebius Token Factory](https://tokenfactory.nebius.com) API key

### 1. Clone & set up the backend

```bash
cd agent
cp .env.example .env
# Add your NEBIUS_API_KEY to .env

python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python server.py
```

Backend runs at `http://localhost:8000`.

### 2. Set up the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000` and proxies API calls to the backend.

### 3. Compose a pipeline

Open `http://localhost:3000`, type a robot task, select a robot, and hit **Compose Pipeline**.

---

## Tests

Backend tests cover all API endpoints, the pipeline store (persistence, cap, corrupt-file recovery, Redis backend via a fake client), and the ROS2 export/validate flow. The LLM is faked, so tests never call the Nebius API or spend credits.

```bash
cd agent
pip install -r requirements-dev.txt
python -m pytest
```

84 hermetic tests in ~15s (the LLM is faked and the store is forced to the local backend, so tests never hit the Nebius API or Upstash Redis).

Plus nine live browser E2E tests (`pytest -m e2e`): one opens a real share link (`/#p=<id>`) and asserts the pipeline renders from the URL hash; the second drives the editable pipeline view (reorder/remove steps, re-export); the third proves history persists across a reload and a composed pipeline can be reopened from the history panel, tweaked, and re-exported LLM-free; the fourth composes a seeded variation (reworded task, robot switched) and verifies the adaptation card explains the changes; the fifth seeds the session auto-retry tally and asserts the frequent-blip hint appears in live mode and clears when mock mode is chosen; the sixth intercepts the compose stream with canned retries (1, then 3) and asserts the timing line's retry disclosure renders for both counts; the seventh seeds a two-compose session baseline, serves a 60s compose through the stub, and asserts the slow-compose warning appears with the ratio and clears on a normal compose; the eighth opens the simulation dry-run on a mock pipeline and asserts the replay completes, pause freezes the elapsed clock, a same-seed replay reproduces the identical summary, and — after reordering validation ahead of every training step — the replay halts at step 1 with the structural "no trained policy to validate" reason; the ninth asserts the dry-run verdict badge lands on the history card and that reopening the pipeline renders the stored verdict instantly ("last run") with the same seed, with replay reproducing it. They need the backend (:8000) and frontend (:3000) running and `playwright` installed (`pip install -r requirements-dev.txt`); they skip themselves otherwise and are excluded from the default run via the `e2e` marker.

---

## Live Verification

`agent/live_check.py` runs real end-to-end checks against live servers (real Upstash Redis / Nebius LLM where noted). Run it from the `agent/` directory:

| Command | What it proves |
|---------|----------------|
| `python live_check.py share-links [--skip-compose] [--cleanup]` | Boots two independent server processes over the shared Redis store and proves share links resolve across instances — plus health/readiness diagnostics, the share-link rate limit, and (unless `--skip-compose`) a real LLM compose. `--cleanup` deletes the test keys from Redis afterwards. |
| `python live_check.py journey` | Full user journey through the running frontend (:3000) → backend (:8000) proxy: compose (one real LLM call) → export → validate → share-link restore. Reports the compose's `retries` count (and prints a note when the model healed a blip). |
| `python live_check.py edit` | Browser edit flow: compose live, reorder/remove steps, re-export LLM-free, verify the share link points at the edited pipeline (one real LLM call). |

`live_share_link_check.py` is kept as a thin alias for the first command (`python live_share_link_check.py --cleanup` works). All subcommands print a PASS/FAIL report and exit non-zero on failure.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check + pipeline-store backend diagnostics (redis/memory, entry count, Redis connectivity) + rolling compose telemetry (`compose_stats`: samples, avg/p95 latency, retry counts, recent tail) |
| `GET` | `/api/health/ready` | Readiness probe: 503 when Redis is configured but unreachable, else 200 |
| `GET` | `/api/skills` | List all 11 NVIDIA skills |
| `GET` | `/api/skills/{id}` | Get skill details |
| `GET` | `/api/skills/search/{q}` | Search skills by keyword |
| `POST` | `/api/compose` | Decompose task into pipeline + explanation |
| `POST` | `/api/compose/silent` | Pipeline only (faster, cheaper) |
| `POST` | `/api/compose/stream` | SSE stream: thinking + pipeline + logs |
| `GET` | `/api/pipeline/{id}` | Fetch a previously composed pipeline from the store (rate limited: 30 req / 60s per client) |
| `POST` | `/api/pipeline/export` | Generate ROS2 package (accepts `pipeline_id` or inline `pipeline`) |
| `POST` | `/api/pipeline/validate` | Validate generated package files |
| `POST` | `/api/improve` | Re-analyze a pipeline for improvements (accepts `pipeline_id`) |

Every compose (and export) stores the pipeline and returns a `pipeline_id` — downstream calls can reference it instead of re-running the model. Compose responses also carry `retries` (how many LLM round-trips healed via auto-retry; 0 on clean calls), on `/api/compose` (summed across decompose + explain), `/api/compose/silent`, `/api/improve`, and the stream's `done` event.

The pipeline store is backed by **Upstash Redis** when `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` are set (see `agent/.env.example`) — shared links then work across server instances and survive restarts, with entries expiring after 7 days and capped at the 50 most recent. Without those credentials, the server falls back to an in-memory store persisted to `agent/pipeline_store.json` (same cap), so local links still survive restarts; delete the file to clear it.

---

## Cost Awareness

Every pipeline comes with per-step and total cost estimates. The agent is instructed to keep costs reasonable:
- **Simple tasks** (pick and place): under $5
- **Complex tasks** (multi-step assembly): under $10
- **$25 credit budget**: SkillForge can compose ~6-10 full pipelines before exhausting a typical hackathon token budget

---

## Architecture Decisions

**Why Nemotron 30B?** It's instruction-tuned, fast on Token Factory, and strong at structured JSON output — critical for pipeline decomposition.

**Why a static skill catalog?** A fixed registry ensures the agent only selects valid, costed NVIDIA skills. No hallucinated tools. Easy to extend.

**Why decompose before execute?** Breaking tasks into subtasks lets users review, modify, and optimize the pipeline before spending GPU credits.

---

## What's Next

The statused list lives in [docs/ROADMAP.md](docs/ROADMAP.md). Current
candidates (pipeline editor and history/versioning have shipped):

- [ ] **Isaac Sim integration** — Execute pipelines directly in simulation
- [ ] **Expanded skill catalog** — Add Isaac Lab, cuRobo, and more NVIDIA tools
- [ ] **Cost optimization mode** — Agent suggests cheaper alternatives automatically
- [ ] **Multi-robot support** — Compose pipelines for robot swarms
- [ ] **Product naming** — Decide the public name before cutting 0.1.0

Each milestone's changes are tracked in [CHANGELOG.md](CHANGELOG.md); commit
guidelines live in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Team

Built with ❤️ at the Nebius Global AI Hackathon 2026.

---

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and security policy.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

Generated ROS2 packages reference NVIDIA tools which have their own licenses. See https://developer.nvidia.com/licenses
