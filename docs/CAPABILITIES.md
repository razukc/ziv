# Capability Map — Personal AI Track (Nebius x NVIDIA Global AI Hackathon)

Research artifact for a **second submission** (Personal AI Track) alongside
SkillForge. Method: capability-first. We inventory what the stack can actually
do, find the combinations only *this* stack enables, and score problem
candidates against them — so the problem pick falls out of capabilities, not
vibes.

Facts below were captured Sep 5, 2026 from the hackathon pages and vendor
docs, with sources linked. Claims we could not verify are listed under
[Open questions](#4-constraints--open-questions) rather than asserted.

---

## 1. The track, read as two parts

> Build an always-on, private assistant that works for you while keeping your
> data under your control. Give it persistent memory, reusable skills, access
> to the tools and information you choose, and the ability to carry out tasks
> across your daily workflows. Use at least one NVIDIA open source model, and
> use tools such as NVIDIA NemoClaw, OpenShell, Hermes Agent, and Nebius
> Serverless to bring personal AI to assemble, secure, and run your own
> personal AI system.

The track is a complete sentence in **two parts**, and a submission must
satisfy both:

- **Part 1 — the WHAT (the assistant's required properties):** always-on,
  private, data under your control, persistent memory, reusable skills, access
  to the tools and information *you choose*, and the ability to carry out
  tasks across daily workflows.
- **Part 2 — the HOW (the required build method):** at least one NVIDIA open
  source model, plus tools "such as" NemoClaw, OpenShell, Hermes Agent, and
  Nebius Serverless, used to **assemble, secure, and run** your own personal
  AI system. Those three verbs are the organizing principle of this document:
  - **Assemble** — what the agent is made of (memory, skills, channels, tools)
  - **Secure** — how it is locked down (sandbox, egress policy, credentials)
  - **Run** — where it lives 24/7 (always-on runtime, scheduling, compute)

Implication: most entries will submit only Part 1 (or a fragment of it) — a
chat app with memory but no security story, or a demo that isn't actually
always-on. A judge reading this track checks both halves. Stage One
("genuine attempt at the track's stated goal, not a superficial rebrand of an
unrelated idea") and the equally weighted criteria — Technological
Implementation, Design, Potential Impact, Quality of the Idea — all reward
showing the full sentence.

---

## 2. Capability inventory by verb

### Assemble — what the agent is made of

| Capability | What it actually does | Source |
|---|---|---|
| **SKILL.md skills learned from chat** | Hermes Agent writes skills as files with YAML frontmatter (name + description) when a user teaches a format; the skill fires from a fresh conversation later. "Teach once, recall anywhere." | [NVIDIA blog](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/) |
| **Persistent memory + sessions** | Hermes keeps memory, sessions, and scheduled jobs; snapshot/restore preserves them across sandbox rebuilds (credential filter excludes `.env`/`*token*`/`*secret*`). | same |
| **24/7 presence across channels** | OpenClaw connects through 20+ messaging channels (Telegram, Discord, Slack, WhatsApp, email, …), has a web UI, model routing, and self-installs skills from a 17,000+ skill catalog. | [openclaw.ai](https://openclaw.ai/), [Milvus guide](https://milvus.io/blog/openclaw-formerly-clawdbot-moltbot-explained-a-complete-guide-to-the-autonomous-ai-agent.md) |
| **Model routing** | Token Factory serves the Nemotron 3 family with different cost/speed/reasoning profiles — route routine calls to Nano, hard reasoning to Super/Ultra (see stack table). | [TF cookbook](https://github.com/nebius/token-factory-cookbook/tree/main/models/nemotron) |
| **Omni-modal input** | Nemotron-3-Nano-Omni adds multimodal reasoning (text + image/audio-class inputs) for agentic AI. | same |
| **Search as a tool** | Tavily search API; a functional runtime call also qualifies for the $3,000 bonus prize. | [devpost rules](https://nebiusglobalaihackathon.devpost.com/rules) |
| **Integration bridges** | Hermes ships bridges (Slack, Outlook) for messaging; OpenClaw integrates inbox, calendar, email sending, flight check-in. | [NVIDIA blog](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/), [openclaw.ai](https://openclaw.ai/) |

### Secure — how it is locked down

| Capability | What it actually does | Source |
|---|---|---|
| **Network policy as code** | OpenShell enforces `policy.yaml` allowlists: every allowed host/port/verb/binary is declared; anything unlisted returns 403, which the agent treats as a tool error. Egress control is code, not a prompt. | [NVIDIA blog](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/) |
| **Credential brokering** | OpenShell manages credentials at the sandbox proxy — the agent never sees Slack/Outlook/token secrets; auth happens as requests leave the sandbox. | same |
| **Sandbox hardening** | Container hardening with capability drops and process limits; sandboxes isolate agents from the host. | [NemoClaw GitHub](https://github.com/NVIDIA/NemoClaw) |
| **Sandbox orchestration** | NemoClaw manages sandbox lifecycle: guided onboarding, managed inference, network policy, managed integrations, snapshots, CLI aliases for OpenClaw/Hermes/Deep Agents. Apache 2.0, alpha. | [NemoClaw GitHub](https://github.com/NVIDIA/NemoClaw) |
| **Audit trail (black box recorder)** | Agent trajectories are recorded in ATIF format via NeMo Relay in the sandbox image; can stream to Arize Phoenix. Every decision is traceable. | [NVIDIA blog](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/) |

### Run — where it lives 24/7

| Capability | What it actually does | Source |
|---|---|---|
| **Always-on agent runtime** | OpenClaw runs 24/7: cron jobs plus a heartbeat checked every ~30 minutes; it acts on schedules even when nobody is chatting. | [Lenny's guide](https://www.lennysnewsletter.com/p/openclaw-the-complete-guide-to-building), [openclaw.ai](https://openclaw.ai/) |
| **Scheduled cloud compute** | Nebius Serverless AI Jobs run container images as **one-off or scheduled batch workloads** (training, fine-tuning, data processing), auto-releasing compute when done. | [Nebius docs](https://docs.nebius.com/serverless/jobs/manage) |
| **Real-time serving** | Serverless Endpoints serve inference on demand; DevPods give interactive dev environments. All three are container-based, no VM/cluster ops. | [Nebius docs](https://docs.nebius.com/serverless/overview) |
| **State that survives redeploys** | Snapshot/restore preserves skills, memories, sessions, and scheduled jobs across rebuilds — the learned agent persists even when the runtime is recreated. | [NVIDIA blog](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/) |
| **Cost economics** | ~$150 total credits available (see constraints); model routing + short-context routine calls make 24/7 operation affordable. | [devpost resources](https://nebiusglobalaihackathon.devpost.com/resources), [builder terms](https://nebius.com/builders-terms-and-conditions) |

---

## 3. Stack snapshot

| Component | Role (verb) | Status / license | Notes |
|---|---|---|---|
| **Nebius Token Factory** | Run | GA | Serverless inference API, OpenAI-compatible, 60+ open models. |
| **Nemotron-3-Nano-30B-A3B** | Run | NVIDIA open | 30B total / 3B active, 262K ctx; efficient reasoning/chat/coding; already used by SkillForge (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`). |
| **Nemotron-3-Nano-Omni** | Run | NVIDIA open | 30B/3B, 262K; omni-modal reasoning for agentic AI. |
| **Nemotron-3-Super-120B-A12B** | Run | NVIDIA open | 120B/12B, 256K; hybrid MoE "optimized for multi-agent AI"; default model in the NVIDIA NemoClaw/Hermes example. |
| **Nemotron-3-Ultra-550B-A55B** | Run | NVIDIA open | 550B/55B, 256K; flagship, "for the most demanding multi-agent AI and complex reasoning tasks." |
| **Nebius Serverless AI (DevPods / Jobs / Endpoints)** | Run | GA | Container-based serverless compute; Jobs are one-off or scheduled; scale-to-zero. |
| **NVIDIA OpenShell** | Secure | Alpha | Sandbox runtime: network policy as code, credential brokering, hardening. Hosts: macOS, Windows via WSL 2, Linux. |
| **NVIDIA NemoClaw** | Secure + Assemble | Apache 2.0, alpha | Reference stack orchestrating sandboxed agents (OpenClaw default, Hermes, LangChain Deep Agents Code): policies, snapshots, lifecycle, managed inference. |
| **Hermes Agent** | Assemble | Open source (NVIDIA) | Harness: SKILL.md skills, memory, sessions, bridges, scheduled jobs, hooks; ATIF traces. |
| **OpenClaw** | Assemble + Run | Open source | 24/7 agent: cron + heartbeat, 20+ channels, 17k+ self-installing skills, model routing. |
| **Tavily** | Assemble | API w/ free credits | Search-as-a-tool; $3,000 bonus for a runtime call. |
| **SkillForge DNA (ours)** | All | Apache 2.0 | Reusable patterns: registry-grounded tool use, capability gates, per-step cost model + budget-aware prompting, streaming reasoning, telemetry (`compose_stats`, retries), hermetic test discipline, mock mode. |

Sources: [TF cookbook — Nemotron models](https://github.com/nebius/token-factory-cookbook/tree/main/models/nemotron), [NemoClaw GitHub](https://github.com/NVIDIA/NemoClaw), [NVIDIA blog](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/), [Nebius docs](https://docs.nebius.com/serverless/overview), [openclaw.ai](https://openclaw.ai/).

---

## 4. Constraints & open questions

### Honest constraints

- **Alpha software:** NemoClaw is alpha; OpenShell is alpha ("proof of life,"
  per NVIDIA). Expect friction; keep the critical path on the most stable
  pieces (Token Factory API, Serverless Jobs, OpenClaw/Hermes on a normal
  host).
- **Host requirements:** NemoClaw's express install targets supported **DGX
  or WSL** hosts; native Windows is not a supported path (use WSL); Ubuntu
  22.04+ and Docker (root/privileged) are assumed; generic Linux NVIDIA GPU
  hosts need `NEMOCLAW_EXPERIMENTAL=1` or `NEMOCLAW_PROVIDER=install-vllm`.
  OpenShell itself runs on macOS, Windows via WSL 2, and Linux.
- **24/7 runtime reality:** "always-on" needs a machine that is actually on —
  a local host, a cheap VPS, or Nebius Serverless Jobs/Endpoints. The demo
  video must show the agent working while the user is away, not a chat
  session.
- **Credits:** ~$25 Token Factory (devpost form, code
  `NEBIUS-DEVPOST-GLOBAL26`) + up to $50 Token Factory / $50 AI Cloud / $25
  Tavily via the Nebius Builder Program (max per member). Total ≈ **$150**.
  Tokens are cheap; GPU Jobs are the expensive lever — keep jobs demo-scale.
- **Submission rules that shape the build:** working demo URL required; ≤3
  minute public YouTube video with audio covering how Token Factory +
  NVIDIA open models were used; public repo with an open-source license
  visible at the top (we use Apache 2.0); README with setup + run guidance;
  judges are *not required to test* — they may judge from description, images,
  and video alone; pre-existing projects must explain what changed during the
  Submission Period (Aug 26 – Oct 30). Winners announced ~Jan 11, 2027.
- **Prize shape:** Personal AI Track winner = NVIDIA Jetson Orin Nano. Each
  project is eligible for one Overall Award **or** one Track Award, plus one
  Bonus Award ($3,000 Best Use of Tavily). A second submission can win
  independently of SkillForge.

### Open questions (verify before scoping)

- [ ] Does NemoClaw/OpenClaw/Hermes support **Nebius Token Factory as an
      inference provider** directly, or do we need a custom OpenAI-compatible
      endpoint config? (NemoClaw supports "routed inference" per its docs —
      provider list TBD.)
- [ ] Exact **scheduled Jobs** trigger syntax and limits in Nebius Serverless
      (docs say "one-off or scheduled batch workloads" — schedule API TBD).
- [ ] Tavily credit flow: how credits land from the Builder Program, and
      whether the $3k bonus requires the call inside the submitted app vs any
      runtime call.
- [ ] Whether OpenShell/NemoClaw install cleanly on **our actual host** (OS,
      WSL availability, Docker perms) — do a spike early, it's the top
      schedule risk.
- [ ] OpenClaw channel list for the demo: which channel (Telegram bot is
      easiest to demo) is permitted without a paid tier.
- [ ] Exact model IDs on Token Factory for Super/Ultra (cookbook lists
      `Nemotron-3-Super-120B-A12B` / `Nemotron-3-Ultra-550B-A55B`; Nano ID is
      confirmed in SkillForge's code).

---

## 5. Rare combinations (the moat)

These are the combinations the consumer market cannot offer, stated as verb
pairs. A submission should visibly demonstrate at least one of them:

1. **Provable non-exfiltration (Secure + Assemble)** — an agent that can read
   your most sensitive data (documents, mail, files) but *cannot* leak it:
   egress allowlist + credential brokering. The demo moment writes itself:
   watch the agent try to reach the public internet and get a 403.
2. **The black box recorder (Secure + Run)** — every agent action recorded in
   ATIF traces. Auditability as a feature: "your agent has a flight recorder."
3. **Per-domain isolation (Secure + Assemble)** — a *fleet* of sandboxed
   specialist agents (finance agent, admin agent, health agent), each locked
   to its own data, instead of one all-access agent that holds everything.
   NemoClaw manages multiple sandboxes; isolation is the architecture.
4. **Cost-aware autonomy (Run + Assemble)** — model routing (Nano for routine,
   Super/Ultra for hard) plus per-task budgets, so always-on is affordable
   within the credit envelope. SkillForge's cost model and budget-aware
   prompting carry over directly.
5. **Teach-once persistence (Assemble + Run)** — skills learned from
   conversation survive rebuilds via snapshot/restore, so the agent compounds
   instead of starting over.

---

## 6. Problem candidates + scoring matrix

Provisional scores (1–5, higher = better), to be re-scored when a candidate
is picked. "Needs all 3 verbs" is the gate: a candidate that only exercises
two verbs is weaker *for this track* than one that needs the full sentence.

| Candidate | Needs all 3 verbs | Stage One fit | Tech Impl. | Design | Impact | Idea | Feasibility (8 wks) | Demoability |
|---|---|---|---|---|---|---|---|---|
| **Accountable life-admin** — for someone you're responsible for (aging parent, household): renewals, paperwork, appointments; audit trail + egress lock + approval pauses are the core | 5 | 5 | 5 | 4 | 5 | 4 | 4 | 5 |
| **Isolated agent fleet** — freelancer's work agent + personal agent in separate sandboxes; domain isolation is the pitch | 4 | 4 | 5 | 4 | 4 | 5 | 3 | 4 |
| **Self-budgeting always-on agent** — multi-channel, routes Nano/Super/Ultra against a monthly token budget it reports on | 4 | 4 | 4 | 4 | 4 | 5 | 5 | 4 |

> **Status (Sep 7, 2026):** the second submission direction has been chosen
> and refined — a haptic AI companion for deaf-blind users (ESP32-S3 wearable,
> Nemotron-3-Nano-Omni hearing via Nebius Token Factory, vibro-braille output).
> See [HAPTIC_COMPANION_PLAN.md](./HAPTIC_COMPANION_PLAN.md) for the concept,
> architecture, MVP milestones, and demo script.

### One-line summaries

- **Accountable life-admin:** "the agent for the stuff you forget, for the
  people you're responsible for" — the security + audit layer is what makes it
  trustworthy enough to deploy. Strongest demo: a 403 moment, an approval
  pause, a reminder that arrived because the agent ran overnight.
- **Isolated agent fleet:** separation of domains as the privacy story — no
  single agent holds everything; NemoClaw's multi-sandbox orchestration is
  the differentiator.
- **Self-budgeting agent:** cost-aware autonomy — the agent routes its own
  model per task and reports its spend; always-on for pennies. Cheapest to
  build, but the least "security-heavy" of the three.

---

## How this document is used

1. Pick a candidate (or fold two together) → write a one-page problem brief.
2. Resolve the open questions that gate the chosen candidate (spike the
   OpenShell/NemoClaw install first — it is the top schedule risk).
3. Scope the build around the three verbs: what we assemble, how we secure
   it, where it runs — and what the demo video shows for each verb.
4. Feed the verified capability facts into the Devpost write-up so claims are
   grounded.