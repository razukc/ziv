"""Live verification CLI for SkillForge.

Runs real end-to-end checks against live servers and services. Subcommands:

  share-links  Boot two independent server processes over the shared Upstash
               Redis store and prove share links resolve across instances
               (plus health/readiness and share-link rate-limit checks).
                 --skip-compose  skip the real LLM /api/compose/silent check
                 --cleanup       delete the test pipeline keys from Redis
                                 after the run
  journey      Full user journey against a running stack (frontend :3000
               proxying to the backend :8000): compose (one real LLM call)
               -> export -> validate -> share-link restore.
  edit         Browser edit flow against a running stack: compose live (one
               real LLM call), reorder/remove steps, re-export LLM-free, and
               verify the share link points at the edited pipeline.

Run from the agent/ directory, e.g.::

    python live_check.py share-links --cleanup
    python live_check.py journey
    python live_check.py edit

Exit code 0 = all checks passed, 1 = failure.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

import httpx
from dotenv import load_dotenv

from e2e_helpers import browser_page, wait_hydrated
from server import SHARE_LINK_RATE_LIMIT

FRONTEND = "http://localhost:3000"
BACKEND = "http://localhost:8000"
PORT_A = 8011
PORT_B = 8012


# --- tiny PASS/FAIL harness -----------------------------------------------

class CheckFailed(Exception):
    pass


def make_check():
    """Returns a check(label, ok, detail='') printer that raises on failure."""
    state = {"checks": 0}

    def check(label, ok, detail=""):
        state["checks"] += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
        if not ok:
            raise CheckFailed(label)

    def count():
        return state["checks"]

    return check, count


def require_servers_up() -> None:
    from e2e_helpers import servers_up
    if not servers_up(FRONTEND, BACKEND):
        raise SystemExit(
            "Servers not reachable — start the backend (cd agent && python server.py, "
            "port 8000) and the frontend (cd frontend && npm run dev, port 3000).")


def _load_redis():
    from upstash_redis import Redis
    return Redis(url=os.environ["UPSTASH_REDIS_REST_URL"],
                 token=os.environ["UPSTASH_REDIS_REST_TOKEN"])


# --- share-links ----------------------------------------------------------

def sample_pipeline(task: str, robot: str = "unitree-g1") -> dict:
    return {
        "task": task,
        "robot": robot,
        "task_type": "manipulation",
        "subtasks": [
            {"order": 1, "name": "scene-creation", "description": "Build 3D environment in Isaac Sim",
             "skill_id": "scene-creation", "estimated_cost_usd": 0.15, "gpu_required": True},
            {"order": 2, "name": "policy-training", "description": "Train policy on captured demonstrations",
             "skill_id": "policy-training-gr00t", "estimated_cost_usd": 2.00, "gpu_required": True},
            {"order": 3, "name": "deployment", "description": "Export ROS2 package",
             "skill_id": "policy-deployment", "estimated_cost_usd": 0.05, "gpu_required": False},
        ],
        "total_estimated_cost_usd": 2.20,
        "estimated_time_minutes": 9,
        "risk_assessment": "low",
        "notes": "live multi-instance share-link test",
    }


def _wait_for_health(base: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/api/health", timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.4)
    return False


def _start_server(port: int, log_path: str) -> subprocess.Popen:
    here = os.path.dirname(os.path.abspath(__file__))
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=here,
        stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
    )


def _stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=8)
    # Release the log file so its temp dir can be removed (Windows keeps
    # handles open until the parent closes them).
    if proc.stdout is not None:
        proc.stdout.close()


def cleanup_pipelines(created_ids: list) -> int:
    """Delete test pipeline keys and their sorted-set entries from Redis.

    Removes each ``sf:pipeline:{id}`` value key and prunes the ids from the
    ``sf:pipeline:created`` insertion-order sorted set, so the cap isn't
    filled with test data. Returns how many keys actually existed.
    """
    if not created_ids:
        print("  [cleanup] no pipelines were created this run - nothing to clean")
        return 0
    redis = _load_redis()
    deleted = 0
    for pid in created_ids:
        key = f"sf:pipeline:{pid}"
        if redis.get(key) is not None:
            redis.delete(key)
            deleted += 1
    redis.zrem("sf:pipeline:created", *created_ids)
    print(f"  [cleanup] deleted {deleted}/{len(created_ids)} pipeline key(s): {', '.join(created_ids)}")
    return deleted


def cmd_share_links(args) -> int:
    check, count = make_check()
    base_a = f"http://127.0.0.1:{PORT_A}"
    base_b = f"http://127.0.0.1:{PORT_B}"

    created_ids: list = []
    procs = []
    # ignore_cleanup_errors: Windows can hold the log file briefly after a
    # process is killed; a leftover temp log is harmless.
    log_dir = tempfile.TemporaryDirectory(prefix="skillforge-live-",
                                          ignore_cleanup_errors=True)
    try:
        print("== Booting two independent server processes ==")
        procs = [
            _start_server(PORT_A, os.path.join(log_dir.name, "a.log")),
            _start_server(PORT_B, os.path.join(log_dir.name, "b.log")),
        ]
        for label, base, proc in (("A", base_a, procs[0]), ("B", base_b, procs[1])):
            if not _wait_for_health(base):
                print(f"Instance {label} failed to become healthy (pid {proc.pid}); log tail:")
                with open(os.path.join(log_dir.name, f"{label.lower()}.log")) as f:
                    print("".join(f.readlines()[-15:]))
                return 1
            print(f"  instance {label} healthy at {base} (pid {proc.pid})")
            h = httpx.get(f"{base}/api/health", timeout=15).json()
            check(f"instance {label} reports redis backend",
                  h["pipeline_store"]["backend"] == "redis",
                  f"backend={h['pipeline_store']['backend']}")
            check(f"instance {label} reports redis connected",
                  h["pipeline_store"]["redis_connected"] is True)
            r_ready = httpx.get(f"{base}/api/health/ready", timeout=15)
            check(f"instance {label} readiness probe -> 200",
                  r_ready.status_code == 200, f"http {r_ready.status_code}")

        a_gets = 0  # count GETs against instance A: they consume its budget

        # --- Direction A -> B ---------------------------------------------
        print("\n== Share link created on instance A, resolved on instance B ==")
        task_a = "Pick up the red block and place it in the tray"
        pipeline_a = sample_pipeline(task_a)
        r = httpx.post(f"{base_a}/api/pipeline/export",
                       json={"task": task_a, "robot": "unitree-g1", "pipeline": pipeline_a}, timeout=30)
        check("POST /api/pipeline/export on A stores pipeline", r.status_code == 200,
              f"http {r.status_code}")
        pid_a = r.json()["pipeline_id"]
        created_ids.append(pid_a)
        check("A returned a content-hash pipeline id",
              pid_a.startswith("p") and len(pid_a) == 11, pid_a)

        # Prove the value actually lives in Upstash Redis, not a local file.
        raw = _load_redis().get(f"sf:pipeline:{pid_a}")
        check("pipeline present in Upstash Redis under sf:pipeline:{id}", raw is not None)
        check("Redis value round-trips to the same pipeline",
              json.loads(raw) == pipeline_a)

        r = httpx.get(f"{base_b}/api/pipeline/{pid_a}", timeout=15)
        check("GET /api/pipeline/{id} on instance B -> 200", r.status_code == 200,
              f"http {r.status_code}")
        check("B returned the identical pipeline (task + all subtasks)",
              r.json()["pipeline"] == pipeline_a)
        a_gets += 1
        check("same id also resolves on instance A",
              httpx.get(f"{base_a}/api/pipeline/{pid_a}", timeout=15).status_code == 200)
        print(f"  share link: {base_b}/#p={pid_a}")

        # --- Direction B -> A ---------------------------------------------
        print("\n== Share link created on instance B, resolved on instance A (bidirectional) ==")
        task_b = "Inspect the conveyor belt for defects and sort parts"
        pipeline_b = sample_pipeline(task_b)
        r = httpx.post(f"{base_b}/api/pipeline/export",
                       json={"task": task_b, "robot": "unitree-g1", "pipeline": pipeline_b}, timeout=30)
        check("POST /api/pipeline/export on B stores pipeline", r.status_code == 200,
              f"http {r.status_code}")
        pid_b = r.json()["pipeline_id"]
        created_ids.append(pid_b)
        a_gets += 1
        r = httpx.get(f"{base_a}/api/pipeline/{pid_b}", timeout=15)
        check("GET /api/pipeline/{id} on instance A -> 200", r.status_code == 200,
              f"http {r.status_code}")
        check("A returned the identical pipeline", r.json()["pipeline"] == pipeline_b)
        print(f"  share link: {base_a}/#p={pid_b}")

        # --- Negative control ---------------------------------------------
        print("\n== Negative control: unknown id 404s (no false positives) ==")
        r = httpx.get(f"{base_b}/api/pipeline/pbogus12345", timeout=15)
        check("unknown pipeline id on B -> 404", r.status_code == 404, f"http {r.status_code}")

        # --- Bonus: real LLM compose (unless skipped) ----------------------
        if not args.skip_compose:
            print("\n== Bonus: real /api/compose/silent on A, resolved on B ==")
            r = httpx.post(f"{base_a}/api/compose/silent",
                           json={"task": "Detect the red cylinder and grasp it with the gripper",
                                 "robot": "unitree-g1"}, timeout=120)
            if r.status_code != 200:
                print(f"  [SKIP] LLM compose failed (http {r.status_code}: {r.text[:200]}) - "
                      "mechanism checks above already prove the share-link path")
            else:
                pid_c = r.json()["pipeline_id"]
                created_ids.append(pid_c)
                retries_c = r.json().get("retries", 0)
                if retries_c:
                    print(f"  (this compose auto-retried {retries_c}×, healed on its own)")
                tool_c = r.json().get("tool_calls", 0)
                if tool_c:
                    print(f"  (decomposition grounded via {tool_c} registry tool call(s))")
                else:
                    print("  (decomposition answered from the prompt — no registry tool calls)")
                r2 = httpx.get(f"{base_b}/api/pipeline/{pid_c}", timeout=15)
                check("LLM-generated pipeline id resolves on B", r2.status_code == 200,
                      f"http {r2.status_code}")
                check("B returned the same task the LLM composed",
                      r2.json()["pipeline"].get("task") == r.json()["pipeline"].get("task"))
                print(f"  share link: {base_b}/#p={pid_c}")

        # --- Rate limiting -------------------------------------------------
        print("\n== Rate limiting: share-link endpoint enforces per-client budget ==")
        codes = []
        for _ in range(45):
            r = httpx.get(f"{base_a}/api/pipeline/{pid_a}", timeout=15)
            codes.append(r.status_code)
            if r.status_code == 429:
                break
        ok_count = sum(1 for c in codes if c == 200)
        expected = SHARE_LINK_RATE_LIMIT - a_gets  # budget shared with earlier A GETs
        check("share-link fetches capped at the per-client budget",
              ok_count == expected and codes[-1] == 429,
              f"{ok_count} OK before first 429 (expected {expected})")
        r_last = httpx.get(f"{base_a}/api/pipeline/{pid_a}", timeout=15)
        check("exhausted budget keeps returning 429", r_last.status_code == 429,
              f"http {r_last.status_code}")
        retry_after = r_last.headers.get("Retry-After", "0")
        check("429 carries a positive Retry-After",
              retry_after.isdigit() and int(retry_after) >= 1, f"Retry-After={retry_after}")

        print(f"\nALL {count()} CHECKS PASSED - share links resolve across two live "
              "server processes via Upstash Redis.")
        return 0
    finally:
        for proc in procs:
            _stop_server(proc)
        log_dir.cleanup()
        if args.cleanup:
            try:
                cleanup_pipelines(created_ids)
            except Exception as e:
                print(f"  [cleanup] WARNING: could not clean Upstash Redis: {e}")


# --- journey --------------------------------------------------------------

def cmd_journey(args) -> int:
    require_servers_up()
    check, count = make_check()
    c = httpx.Client(base_url=FRONTEND, timeout=180)

    print("== 1. Health via the frontend proxy ==")
    r = c.get("/api/health")
    check("proxy -> /api/health 200", r.status_code == 200, f"http {r.status_code}")
    store = r.json()["pipeline_store"]
    print(f"  backend mode: {store['backend']}, entries: {store['entries']}, "
          f"redis_connected: {store['redis_connected']}")
    stats = r.json().get("compose_stats", {})
    if stats:
        print(f"  compose_stats: samples={stats.get('samples', 0)} "
              f"avg={stats.get('avg_seconds', 0)}s p95={stats.get('p95_seconds', 0)}s "
              f"retried={stats.get('retried_composes', 0)}")

    print("\n== 2. Compose (real LLM) ==")
    r = c.post("/api/compose", json={"task": args.task, "robot": "unitree-g1"})
    check("POST /api/compose 200", r.status_code == 200, f"http {r.status_code}")
    composed = r.json()
    pid = composed["pipeline_id"]
    pipeline = composed["pipeline"]
    check("compose returned a pipeline id", pid.startswith("p"), pid)
    check("compose returned subtasks", len(pipeline.get("subtasks", [])) > 0,
          f"{len(pipeline.get('subtasks', []))} steps")
    check("explanation present", bool(composed.get("explanation")))
    retries = composed.get("retries", None)
    check("compose reports its auto-retry count",
          isinstance(retries, int) and retries >= 0, retries)
    print(f"  task_type: {pipeline.get('task_type')}, "
          f"cost: ${pipeline.get('total_estimated_cost_usd')}, "
          f"steps: {[s['skill_id'] for s in pipeline.get('subtasks', [])]}")
    if retries:
        print(f"  auto-retried {retries}× during this compose (healed on its own)")
    tool_calls = composed.get("tool_calls", None)
    check("compose reports its registry tool-call count",
          isinstance(tool_calls, int) and tool_calls >= 0, tool_calls)
    if tool_calls:
        print(f"  decomposition grounded via {tool_calls} registry tool call(s)")

    print("\n== 3. Export (ROS2 package) ==")
    r = c.post("/api/pipeline/export",
               json={"task": args.task, "robot": "unitree-g1", "pipeline_id": pid})
    check("POST /api/pipeline/export 200", r.status_code == 200, f"http {r.status_code}")
    export = r.json()
    check("export kept the same pipeline id", export.get("pipeline_id") == pid,
          export.get("pipeline_id"))
    files = export.get("files", {})
    required = ["package.xml", "CMakeLists.txt", "pipeline.json",
                "launch/pipeline.launch.py", "README.md"]
    missing = [f for f in required if f not in files]
    check("export contains all required files", not missing, f"missing: {missing}")
    print(f"  package: {export.get('package_name')}, hash: {export.get('pipeline_hash')}")

    print("\n== 4. Validate ==")
    r = c.post("/api/pipeline/validate",
               json={"files": files, "package_name": export.get("package_name", "")})
    check("POST /api/pipeline/validate 200", r.status_code == 200, f"http {r.status_code}")
    report = r.json()
    check("validation report generated", "score" in report and "valid" in report)
    print(f"  score: {report['score']}/100, valid: {report['valid']}, "
          f"errors: {len(report['errors'])}, warnings: {len(report['warnings'])}")
    for w in report["warnings"][:3]:
        print(f"    warn: {w['file']}: {w['message']}")
    check("generated package validates cleanly",
          report["valid"] and report["errors"] == [],
          f"score {report['score']}/100")

    print("\n== 5. Share-link restore ==")
    r = c.get(f"/api/pipeline/{pid}")
    check("GET /api/pipeline/{id} via proxy 200", r.status_code == 200, f"http {r.status_code}")
    restored = r.json()["pipeline"]
    check("restored pipeline identical to composed", restored == pipeline)
    check("restored pipeline still has all subtasks",
          restored.get("subtasks") == pipeline.get("subtasks"))

    print(f"\nALL {count()} CHECKS PASSED")
    print(f"Share link: {FRONTEND}/#p={pid}")
    return 0


# --- edit -----------------------------------------------------------------

def cmd_edit(args) -> int:
    require_servers_up()
    check, count = make_check()
    export_bodies: list = []
    export_responses: list = []

    with browser_page() as page:
        page.on("request",
                lambda r: export_bodies.append(json.loads(r.post_data))
                if r.method == "POST" and r.url.endswith("/api/pipeline/export") else None)
        page.on("response",
                lambda r: export_responses.append(r.json())
                if r.url.endswith("/api/pipeline/export") and r.ok else None)

        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        wait_hydrated(page)
        # Switch to live mode via the segmented control in the compose box.
        # Synthetic pointer events are unreliable in some environments, so
        # dispatch JS clicks and retry until aria-pressed flips (clicks issued
        # before hydration are no-ops).
        live = False
        for _ in range(20):
            page.wait_for_timeout(400)
            pressed = page.evaluate(
                "document.querySelector('[data-mode=live]')?.getAttribute('aria-pressed')")
            if pressed == "true":
                live = True
                break
            page.evaluate("document.querySelector('[data-mode=live]')?.click()")
        check("mode switch set to live", live)

        # Compose a real pipeline (one LLM call).
        page.locator(".suggestion-chip").first.click()
        page.get_by_role("button", name="compose", exact=True).click()
        page.get_by_role("button", name="edit steps").wait_for(timeout=120000)
        print("[1] live compose done")

        # Export #1 - original pipeline.
        page.get_by_text("Generate ROS2 Package").click()
        page.get_by_text("package ready").wait_for(timeout=30000)
        for i, b in enumerate(export_bodies):
            print(f"  body[{i}] keys={sorted(b.keys())} pipeline_id={b.get('pipeline_id')!r}")
        check("first export carried the pipeline_id",
              len(export_bodies) == 1 and export_bodies[0].get("pipeline_id"),
              f"{len(export_bodies)} export(s)")
        first_id = export_responses[0]["pipeline_id"]
        print(f"[2] first export id={first_id}")

        # Edit: swap the first two steps, remove the third, done.
        page.get_by_role("button", name="edit steps").click()
        page.get_by_text("edit mode — reorder").wait_for(timeout=10000)
        page.get_by_title("move down").first.click()
        page.get_by_title("remove step").nth(2).click()
        page.get_by_role("button", name="done").click()
        page.get_by_text("edited — re-export to publish a new link").wait_for(timeout=10000)
        print("[3] edited (swapped + removed a step)")

        # Export #2 - edited pipeline must NOT carry the stale id.
        page.get_by_text("re-export edited pipeline").click()
        page.get_by_text("package ready").wait_for(timeout=30000)
        check("second export happened (edited re-export)",
              len(export_bodies) == 2, f"{len(export_bodies)} export(s)")
        check("edited export omits the stale pipeline_id",
              "pipeline_id" not in export_bodies[1], f"keys={sorted(export_bodies[1])}")
        second_id = export_responses[1]["pipeline_id"]
        check("edited export produced a new pipeline id", second_id != first_id,
              f"{first_id} -> {second_id}")
        print(f"[4] second export id={second_id} (pipeline_id omitted)")

        # URL hash and share link now point at the edited pipeline.
        page.wait_for_timeout(500)
        check("url hash points at the edited pipeline id",
              f"#p={second_id}" in page.evaluate("() => window.location.hash"),
              page.evaluate("() => window.location.hash"))
        check("edited pipeline id rendered on the page",
              second_id in page.locator("body").inner_text())
        print("[5] share link updated to the edited pipeline id")

        print(f"\nALL {count()} CHECKS PASSED - re-export was LLM-free (no pipeline_id sent).")
        return 0


# --- CLI ------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Live verification for SkillForge (see module docstring).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sl = sub.add_parser("share-links", help="cross-instance share links over Upstash Redis")
    p_sl.add_argument("--skip-compose", action="store_true",
                      help="skip the real LLM-backed /api/compose/silent check")
    p_sl.add_argument("--cleanup", action="store_true",
                      help="delete the test pipeline keys from Upstash Redis after the run")
    p_sl.set_defaults(func=cmd_share_links)

    p_j = sub.add_parser("journey", help="full compose -> export -> validate -> restore journey")
    p_j.add_argument("--task", default="Pick up the red cylinder and place it on the blue tray",
                     help="task to compose (one real LLM call)")
    p_j.set_defaults(func=cmd_journey)

    p_e = sub.add_parser("edit", help="browser edit flow with LLM-free re-export")
    p_e.set_defaults(func=cmd_edit)

    args = parser.parse_args(argv)
    load_dotenv()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CheckFailed as e:
        print(f"\nFAILED at check: {e}")
        sys.exit(1)
    except AssertionError as e:
        print(f"\nFAILED: {e}")
        sys.exit(1)
