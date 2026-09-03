import json

import server
from validation import _xml_tag_balance_ok


def test_export_with_inline_pipeline(client, sample_pipeline):
    r = client.post("/api/pipeline/export", json={
        "task": sample_pipeline["task"], "robot": "unitree-g1", "pipeline": sample_pipeline,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["package_name"] == "sf_g1_manipulation"
    assert data["pipeline_id"].startswith("p")
    assert data["pipeline_hash"]
    files = data["files"]
    for name in ["package.xml", "CMakeLists.txt", "pipeline.json", "launch/pipeline.launch.py", "README.md"]:
        assert name in files, f"missing exported file {name}"
    # The embedded pipeline.json carries the same pipeline_id and hash.
    pjson = json.loads(files["pipeline.json"])
    assert pjson["metadata"]["pipeline_id"] == data["pipeline_id"]
    assert pjson["metadata"]["pipeline_hash"] == data["pipeline_hash"]
    # Every step appears as a node in the launch file.
    assert files["launch/pipeline.launch.py"].count("Node(") == 3


def test_export_by_pipeline_id_does_not_redecompose(client, fake_agent, sample_pipeline):
    pid = server.store_pipeline(sample_pipeline)
    r = client.post("/api/pipeline/export", json={
        "task": "ignored", "robot": "unitree-g1", "pipeline_id": pid,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["pipeline_id"] == pid
    assert "gr00t-n1-finetune" in data["files"]["CMakeLists.txt"]
    # Deterministic: exporting the same id twice yields the same hash.
    r2 = client.post("/api/pipeline/export", json={"task": "x", "robot": "unitree-g1", "pipeline_id": pid})
    assert r2.json()["pipeline_hash"] == data["pipeline_hash"]


def test_reexport_edited_inline_pipeline_is_llm_free(client, fake_agent, sample_pipeline):
    """A human-edited pipeline (remove a step, reorder the rest) re-exports
    from the inline payload with zero LLM calls and its own content-hash id."""
    edited = dict(sample_pipeline)
    subtasks = [dict(s) for s in sample_pipeline["subtasks"]]
    # Remove the middle step, then swap the remaining two so the order changes.
    subtasks.pop(1)
    subtasks[0], subtasks[1] = subtasks[1], subtasks[0]
    for i, st in enumerate(subtasks, 1):
        st["order"] = i
    edited["subtasks"] = subtasks
    edited["total_estimated_cost_usd"] = round(
        sum(s["estimated_cost_usd"] for s in subtasks), 2)

    r = client.post("/api/pipeline/export", json={
        "task": edited["task"], "robot": "unitree-g1", "pipeline": edited,
    })
    assert r.status_code == 200
    data = r.json()
    assert fake_agent.calls == [], f"LLM was called: {fake_agent.calls}"
    assert data["pipeline_id"].startswith("p")

    # Only the remaining steps end up in the generated package.
    assert data["files"]["launch/pipeline.launch.py"].count("Node(") == 2
    pjson = json.loads(data["files"]["pipeline.json"])
    names = [s["name"] for s in pjson["pipeline"]["subtasks"]]
    assert names == [s["name"] for s in subtasks], "edited order must be preserved"

    # The edited pipeline is stored under its own content-hash id.
    stored = server.PIPELINE_STORE.get(data["pipeline_id"])
    assert stored is not None and stored["subtasks"] == subtasks

    # Re-exporting the same edit is idempotent and still LLM-free.
    r2 = client.post("/api/pipeline/export", json={
        "task": edited["task"], "robot": "unitree-g1", "pipeline": edited,
    })
    assert r2.json()["pipeline_id"] == data["pipeline_id"]
    assert fake_agent.calls == []


def test_get_pipeline_by_id(client, sample_pipeline):
    pid = server.store_pipeline(sample_pipeline)
    r = client.get(f"/api/pipeline/{pid}")
    assert r.status_code == 200
    assert r.json()["pipeline_id"] == pid
    assert r.json()["pipeline"]["task_type"] == "manipulation"


def test_get_pipeline_not_found(client):
    r = client.get("/api/pipeline/does-not-exist")
    assert r.status_code == 404


def test_validate_generated_package(client, sample_pipeline):
    exp = client.post("/api/pipeline/export", json={
        "task": sample_pipeline["task"], "robot": "unitree-g1", "pipeline": sample_pipeline,
    }).json()
    r = client.post("/api/pipeline/validate", json={
        "pipeline_id": exp["pipeline_id"], "package_name": exp["package_name"], "files": exp["files"],
    })
    assert r.status_code == 200
    report = r.json()
    assert report["valid"] is True
    assert report["score"] >= 90
    assert report["errors"] == []


def test_validate_generated_package_has_no_tag_mismatch_warning(client, sample_pipeline):
    """The tag-balance heuristic must not flag well-formed generated XML.

    Regression: a naive `<` / `>` count misread comments, processing
    instructions, and self-closing tags, producing a spurious "17 opens vs
    39 closes" warning on every generated package.
    """
    exp = client.post("/api/pipeline/export", json={
        "task": sample_pipeline["task"], "robot": "unitree-g1", "pipeline": sample_pipeline,
    }).json()
    r = client.post("/api/pipeline/validate", json={
        "pipeline_id": exp["pipeline_id"], "package_name": exp["package_name"], "files": exp["files"],
    })
    report = r.json()
    assert report["score"] == 100
    assert not any("tag mismatch" in w["message"] for w in report["warnings"])


def test_tag_balance_detects_real_mismatch():
    assert _xml_tag_balance_ok(
        "<?xml version=\"1.0\"?><package>\n<!-- a comment <tag> -->\n<name>x</name>\n</package>")
    # Missing a close tag is caught; self-closing tags and PIs don't skew it.
    assert not _xml_tag_balance_ok("<package><name>x</name>")
    assert _xml_tag_balance_ok("<package><empty/><name>x</name></package>")


def test_validate_catches_bad_package(client):
    bad_files = {
        "package.xml": "<package>no license no name</package>",
        "CMakeLists.txt": "nothing useful here",
    }
    r = client.post("/api/pipeline/validate", json={"package_name": "bad_pkg", "files": bad_files})
    assert r.status_code == 200
    report = r.json()
    assert report["valid"] is False
    assert report["score"] < 60
    assert len(report["errors"]) >= 2


def test_validate_missing_required_files(client):
    r = client.post("/api/pipeline/validate", json={"package_name": "empty", "files": {"README.md": "# hi"}})
    report = r.json()
    assert report["valid"] is False
    assert any(e["file"] == "package.xml" for e in report["errors"])