import os
import json
import asyncio
import time
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Annotated
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from reasoning_agent import ReasoningAgent
from skill_registry import SKILL_CATALOG, list_all_skills, get_skill, search_skills
from robot_registry import get_robot, known_robots, validate_pipeline_robot
from pipeline_store import PipelineStore, PIPELINE_STORE_MAX, PIPELINE_STORE_TTL_SECONDS
from ros2_package import build_ros2_package
from validation import validate_package


# Every LLM-composed pipeline (fresh or a seeded variation) is gated against
# the requested robot's anatomy before it is stored: a plan that asks an
# armless robot to use arm skills is rejected with a clear error instead of
# being trusted. Unregistered robot slugs are rejected before the LLM runs,
# so an unknown slug costs nothing.
def _unknown_robot_message(robot: str) -> str:
    return (f"robot '{robot}' is not in the robot registry "
            f"(known: {', '.join(known_robots())}). compose for one of these robots.")


def _require_known_robot(robot: str):
    if get_robot(robot) is None:
        raise HTTPException(status_code=422, detail=_unknown_robot_message(robot))


def _gate_compose(pipeline: dict, robot: str):
    problem = validate_pipeline_robot(pipeline, robot)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


def _run_with_retries(fn, *args, **kwargs):
    """Invoke an LLM-facing agent method, counting healed retries.

    Returns ``(result, retries)``: the agent methods accept an ``on_retry``
    callback that fires per healed failure, so request/response endpoints can
    report the count the same way the SSE stream's done event does.
    """
    retries = 0

    def _count(_attempt, _error):
        nonlocal retries
        retries += 1

    return fn(*args, **kwargs, on_retry=_count), retries


# --- rolling compose telemetry (latency + healed retries) ----------------------
# In-process ring of recent composes so ops can see live-mode health from
# /api/health without standing up external metrics. Thread-safe because the
# compose endpoints run on the threadpool while /api/health can run anywhere.
_COMPOSE_TELEMETRY_MAX = 20
_compose_telemetry: deque = deque(maxlen=_COMPOSE_TELEMETRY_MAX)
_compose_telemetry_lock = threading.Lock()


def _record_compose(endpoint: str, seconds: float, retries: int):
    """Append one finished compose to the rolling ring."""
    entry = {
        "endpoint": endpoint,
        "seconds": round(seconds, 1),
        "retries": retries,
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with _compose_telemetry_lock:
        _compose_telemetry.append(entry)


def _compose_stats() -> dict:
    """Summary + the tail of the ring for /api/health."""
    with _compose_telemetry_lock:
        entries = list(_compose_telemetry)
    if not entries:
        return {"samples": 0, "recent": []}
    secs = [e["seconds"] for e in entries]
    ordered = sorted(secs)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {
        "samples": len(entries),
        "avg_seconds": round(sum(secs) / len(secs), 1),
        "p95_seconds": round(p95, 1),
        "avg_retries": round(sum(e["retries"] for e in entries) / len(entries), 2),
        "retried_composes": sum(1 for e in entries if e["retries"] > 0),
        "recent": entries[-10:],
    }
    return pipeline

load_dotenv()

app = FastAPI(title="SkillForge API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = None


# ---------------------------------------------------------------------------
# Pipeline store.
#
# The PipelineStore class itself lives in pipeline_store.py; this module owns
# the process-wide instance and thin helpers so routes (and tests that swap
# the store) keep one indirection point.
# ---------------------------------------------------------------------------
PIPELINE_STORE = PipelineStore()


def store_pipeline(pipeline: dict) -> str:
    """Store a pipeline and return its stable content-hash id."""
    return PIPELINE_STORE.store(pipeline)


def load_pipeline_store():
    """(Re)load the local fallback store from disk (no-op in Redis mode)."""
    if not PIPELINE_STORE.is_remote:
        PIPELINE_STORE._load_from_disk()


def save_pipeline_store():
    """Persist the local fallback store to disk (no-op in Redis mode)."""
    if not PIPELINE_STORE.is_remote:
        PIPELINE_STORE._save_to_disk()


# Health checks ping Redis through the REST API; cache the result briefly so
# frequent LB polls don't burn Upstash request quota.
REDIS_HEALTH_CACHE_TTL_SECONDS = 15
_redis_health_cache = {"mono": None, "ok": None, "at_iso": None}

# Per-client rate limit for share-link resolution (GET /api/pipeline/{id}).
# Deters ID enumeration/scraping. Fixed window per peer IP, enforced
# in-process: with multiple server instances each enforces its own window.
SHARE_LINK_RATE_LIMIT = 30                 # requests per window per client
SHARE_LINK_RATE_WINDOW_SECONDS = 60
_share_link_limiter_lock = threading.Lock()
_share_link_limiter: dict = {}  # client_key -> [window_start_monotonic, count]


def get_agent():
    global agent
    if agent is None:
        api_key = os.environ.get("NEBIUS_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="NEBIUS_API_KEY not set")
        agent = ReasoningAgent()
    return agent


class TaskRequest(BaseModel):
    task: str
    robot: str = "unitree-g1"
    # Optional existing pipeline used as the seed for a variation compose:
    # the agent adapts it to the (possibly reworded) task/robot instead of
    # decomposing from scratch. Inline only — callers send the displayed
    # pipeline, so no extra store round-trip is needed.
    seed_pipeline: Optional[dict] = None


class PipelineRefRequest(TaskRequest):
    """Accepts an optional pre-generated pipeline (by id or inline) so downstream
    endpoints don't re-invoke the LLM and risk getting a different pipeline
    than the one already shown in the UI.
    """
    pipeline_id: str = ""
    pipeline: Optional[dict] = None

    def resolve_pipeline(self, agent):
        """Resolve (pipeline, pipeline_id): stored, inline, or freshly composed.

        The pipeline_id is the referenced one when it exists in the store,
        otherwise a freshly computed content-hash id for the resolved
        pipeline (stored so share links keep working). Only the fallback
        branch touches the LLM.
        """
        if self.pipeline_id and PIPELINE_STORE.get(self.pipeline_id) is not None:
            return PIPELINE_STORE[self.pipeline_id], self.pipeline_id
        if self.pipeline is not None:
            return self.pipeline, store_pipeline(self.pipeline)
        pipeline = agent.decompose_task(self.task, self.robot)
        return pipeline, store_pipeline(pipeline)


class TaskResponse(BaseModel):
    pipeline: dict
    explanation: str = ""
    pipeline_id: str = ""
    # How many LLM round-trips had to be retried to produce this response
    # (0 on clean calls) so API clients can tell a blip healed.
    retries: int = 0


def _redis_connected(store) -> Optional[bool]:
    """Cached ping against the Redis store; None when not in Redis mode.

    Results are cached for REDIS_HEALTH_CACHE_TTL_SECONDS so health polls
    don't hammer the Upstash REST API.
    """
    if not store.is_remote:
        return None
    cached = _redis_health_cache
    now = time.monotonic()
    if cached["mono"] is not None and now - cached["mono"] < REDIS_HEALTH_CACHE_TTL_SECONDS:
        return cached["ok"]
    ok = store.ping()
    cached.update(
        mono=now,
        ok=ok,
        at_iso=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return ok


def _pipeline_store_status() -> dict:
    """Backend diagnostics shared by /api/health and /api/health/ready."""
    store = PIPELINE_STORE
    return {
        "backend": store.backend,
        "entries": store.count(),
        "redis_connected": _redis_connected(store),
        "redis_checked_at": _redis_health_cache["at_iso"] if store.is_remote else None,
    }


@app.get("/api/health")
def health():
    """Service health plus pipeline-store backend diagnostics.

    Reports which storage mode this deployment runs in (redis vs memory), how
    many pipelines are tracked, and live Redis connectivity.
    """
    return {
        "status": "ok",
        "service": "SkillForge API",
        "pipeline_store": _pipeline_store_status(),
        "compose_stats": _compose_stats(),
    }


@app.get("/api/health/ready")
def ready():
    """Readiness probe for load balancers / orchestrators.

    Returns 200 "ready" while the service can serve traffic, and 503
    "degraded" when the deployment is configured for Redis but the store is
    unreachable (share links would silently stop resolving). Memory-mode
    deployments are always ready: the local fallback is a supported mode.
    """
    status = _pipeline_store_status()
    connected = status["redis_connected"]
    payload = {
        "status": "ready" if connected is not False else "degraded",
        "service": "SkillForge API",
        "pipeline_store": status,
    }
    if connected is False:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/skills")
def get_skills():
    return list_all_skills()


@app.get("/api/skills/{skill_id}")
def get_skill_by_id(skill_id: str):
    skill = get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found")
    return skill


@app.get("/api/skills/search/{query}")
def search_skills_endpoint(query: str):
    return search_skills(query)


@app.post("/api/compose")
def compose_pipeline(request: TaskRequest):
    t0 = time.monotonic()
    try:
        _require_known_robot(request.robot)
        a = get_agent()
        pipeline, retries = _run_with_retries(
            a.decompose_task, request.task, request.robot, seed_pipeline=request.seed_pipeline)
        _gate_compose(pipeline, request.robot)
        pipeline_id = store_pipeline(pipeline)
        explanation, more = _run_with_retries(a.explain_pipeline, pipeline)
        _record_compose("compose", time.monotonic() - t0, retries + more)
        return TaskResponse(pipeline=pipeline, explanation=explanation,
                            pipeline_id=pipeline_id, retries=retries + more)
    except HTTPException:
        raise  # capability-gate rejections must keep their 422 + message
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Agent returned invalid JSON: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/compose/silent")
def compose_pipeline_silent(request: TaskRequest):
    """Compose pipeline without explanation (faster, cheaper)."""
    t0 = time.monotonic()
    try:
        _require_known_robot(request.robot)
        a = get_agent()
        pipeline, retries = _run_with_retries(
            a.decompose_task, request.task, request.robot, seed_pipeline=request.seed_pipeline)
        _gate_compose(pipeline, request.robot)
        pipeline_id = store_pipeline(pipeline)
        _record_compose("silent", time.monotonic() - t0, retries)
        return {"pipeline": pipeline, "pipeline_id": pipeline_id, "retries": retries}
    except HTTPException:
        raise  # capability-gate rejections must keep their 422 + message
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/compose/stream")
async def compose_pipeline_stream(request: TaskRequest):
    """Stream thinking, pipeline, and execution logs via SSE.

    Events: thinking, pipeline, explanation, log, error, done.
    """
    async def event_generator():
        # Wall clock for the whole compose so the done event can report
        # "compose took Xs" — a slow LLM round-trip then reads as slow
        # instead of stuck, and retried backoff is included in the time.
        t0 = time.monotonic()
        try:
            # Reject unregistered robots before spending an LLM call.
            if get_robot(request.robot) is None:
                yield f"data: {json.dumps({'type': 'error', 'content': _unknown_robot_message(request.robot)})}\n\n"
                return
            a = get_agent()

            # LLM round-trips auto-retry transient blips; count them so the
            # stream can tell the UI a hiccup happened and healed (otherwise a
            # slow, retried compose is indistinguishable from a hang).
            retries = 0

            def _count_retry(_attempt, _error):
                nonlocal retries
                retries += 1

            # Phase 1: Thinking process
            yield f"data: {json.dumps({'type': 'thinking', 'content': '🧠 Analyzing task...', 'step': 1, 'total': 5})}\n\n"
            await asyncio.sleep(0.3)

            yield f"data: {json.dumps({'type': 'thinking', 'content': f'Detected task type: {request.task}', 'step': 2, 'total': 5})}\n\n"
            await asyncio.sleep(0.2)

            yield f"data: {json.dumps({'type': 'thinking', 'content': f'Selecting skills for {request.robot}...', 'step': 3, 'total': 5})}\n\n"
            await asyncio.sleep(0.3)

            # Phase 2: Generate pipeline. Each LLM round-trip and the log
            # stream are timed individually so the done event can break the
            # compose down into decompose / explain / logs phases — users see
            # which step dominates instead of one opaque total.
            yield f"data: {json.dumps({'type': 'thinking', 'content': 'Generating pipeline with Nemotron...', 'step': 4, 'total': 5})}\n\n"

            t_decompose = time.monotonic()
            pipeline = a.decompose_task(request.task, request.robot,
                                        seed_pipeline=request.seed_pipeline,
                                        on_retry=_count_retry)
            decompose_seconds = round(time.monotonic() - t_decompose, 1)
            problem = validate_pipeline_robot(pipeline, request.robot)
            if problem:
                # Capability gate: never store a plan the robot can't run, and
                # surface why instead of a generic failure.
                yield f"data: {json.dumps({'type': 'error', 'content': problem})}\n\n"
                return
            pipeline_id = store_pipeline(pipeline)

            yield f"data: {json.dumps({'type': 'thinking', 'content': 'Validating skill selections...', 'step': 5, 'total': 5})}\n\n"
            await asyncio.sleep(0.2)

            # Phase 3: Send pipeline
            yield f"data: {json.dumps({'type': 'pipeline', 'pipeline_id': pipeline_id, 'content': pipeline})}\n\n"

            # Phase 4: Generate explanation
            yield f"data: {json.dumps({'type': 'thinking', 'content': 'Generating analysis...', 'step': 6, 'total': 6})}\n\n"

            t_explain = time.monotonic()
            explanation = a.explain_pipeline(pipeline, on_retry=_count_retry)
            explain_seconds = round(time.monotonic() - t_explain, 1)
            yield f"data: {json.dumps({'type': 'explanation', 'content': explanation})}\n\n"

            # Phase 5: Execution logs (simulated)
            t_logs = time.monotonic()
            for i, subtask in enumerate(pipeline['subtasks']):
                skill = SKILL_CATALOG.get(subtask['skill_id'], {})

                yield f"data: {json.dumps({'type': 'log', 'content': f'Starting {subtask['name']}...', 'status': 'running', 'step': i + 1, 'total': len(pipeline['subtasks']), 'skill_id': subtask['skill_id']})}\n\n"
                await asyncio.sleep(0.5)

                yield f"data: {json.dumps({'type': 'log', 'content': f'Loading {skill.get('product', 'tool')}...', 'status': 'running', 'step': i + 1, 'total': len(pipeline['subtasks']), 'skill_id': subtask['skill_id']})}\n\n"
                await asyncio.sleep(0.3)

                yield f"data: {json.dumps({'type': 'log', 'content': f'Processing {subtask['description']}...', 'status': 'running', 'step': i + 1, 'total': len(pipeline['subtasks']), 'skill_id': subtask['skill_id']})}\n\n"
                await asyncio.sleep(0.4)

                yield f"data: {json.dumps({'type': 'log', 'content': f'{subtask['name']} complete', 'status': 'completed', 'step': i + 1, 'total': len(pipeline['subtasks']), 'skill_id': subtask['skill_id']})}\n\n"
                await asyncio.sleep(0.2)

            # Phase 6: Done — the total wall time (LLM round-trips + retry
            # backoff + streaming) so the UI can show "compose took Xs", the
            # retry count for the "(auto-retried Nx)" disclosure, and the
            # per-phase breakdown (decompose / explain / logs).
            logs_seconds = round(time.monotonic() - t_logs, 1)
            if retries:
                yield f"data: {json.dumps({'type': 'notice', 'retries': retries, 'content': 'auto-retried after a model blip'})}\n\n"
            seconds = round(time.monotonic() - t0, 1)
            phases = {"decompose": decompose_seconds, "explain": explain_seconds,
                      "logs": logs_seconds}
            _record_compose("stream", seconds, retries)
            yield f"data: {json.dumps({'type': 'done', 'pipeline_id': pipeline_id, 'content': 'Pipeline ready!', 'total_cost': pipeline['total_estimated_cost_usd'], 'seconds': seconds, 'retries': retries, 'phases': phases})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


def rate_limit_share_links(request: Request) -> None:
    """Fixed-window per-client rate limit for share-link resolution.

    Capped by SHARE_LINK_RATE_LIMIT per SHARE_LINK_RATE_WINDOW_SECONDS, keyed
    on the direct peer IP. Deployments behind a reverse proxy see the proxy's
    IP unless trusted-proxy forwarding is configured (see SECURITY.md). When
    the budget is exhausted the request fails fast with 429 + Retry-After
    instead of hitting the pipeline store.
    """
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    limit = SHARE_LINK_RATE_LIMIT
    window = SHARE_LINK_RATE_WINDOW_SECONDS
    with _share_link_limiter_lock:
        entry = _share_link_limiter.get(client)
        if entry is None or now - entry[0] >= window:
            _share_link_limiter[client] = [now, 1]
            return
        entry[1] += 1
        if entry[1] > limit:
            retry_after = max(1, int(window - (now - entry[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many share-link requests. Slow down and try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        # Opportunistic cleanup: drop entries whose window expired once the
        # table grows large, so client churn can't grow memory unboundedly.
        if len(_share_link_limiter) > 10_000:
            cutoff = now - window
            stale = [k for k, v in _share_link_limiter.items() if v[0] < cutoff]
            for k in stale:
                del _share_link_limiter[k]


@app.get("/api/pipeline/{pipeline_id}")
def get_pipeline_by_id(pipeline_id: str, _: Annotated[None, Depends(rate_limit_share_links)] = None):
    """Fetch a previously generated pipeline from the pipeline store.

    Rate limited per client so share links can't be bulk-scraped.
    """
    pipeline = PIPELINE_STORE.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return {"pipeline_id": pipeline_id, "pipeline": pipeline}


@app.post("/api/improve")
def improve_pipeline(request: PipelineRefRequest):
    """Re-analyze an existing pipeline for improvements."""
    try:
        a = get_agent()
        pipeline, pipeline_id = request.resolve_pipeline(a)
        improvements, retries = _run_with_retries(a.suggest_improvements, pipeline)
        return {"pipeline_id": pipeline_id, "pipeline": pipeline,
                "improvements": improvements, "retries": retries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/export")
def export_pipeline_ros2(request: PipelineRefRequest):
    """Generate a complete ROS2 package from a pipeline.

    Pipeline resolution order: stored pipeline_id, inline pipeline, then
    decompose the task (legacy behaviour). Stored/inline pipelines never
    invoke the LLM, so re-exporting a human-edited pipeline is free.
    """
    try:
        a = get_agent()
        pipeline, pipeline_id = request.resolve_pipeline(a)
        return build_ros2_package(pipeline, request.robot, pipeline_id)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Agent returned invalid JSON: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ValidateRequest(BaseModel):
    files: dict
    package_name: str = ""


@app.post("/api/pipeline/validate")
def validate_pipeline(request: ValidateRequest):
    """Validate a generated ROS2 package for common issues.

    Returns a structured report with errors, warnings, info, a 0-100 score,
    and an overall ``valid`` flag.
    """
    return validate_package(request.files, request.package_name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
