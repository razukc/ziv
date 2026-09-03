"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import { ROBOT_OPTIONS, EXAMPLE_TASKS } from "../lib/mock-data";
import { StatBlock, MetaItem, ExportOption, ExportedFile } from "../components/ui";
import SkillPanel from "../components/skill-panel";
import PipelineTimeline from "../components/pipeline-timeline";
import PlainSummary from "../components/plain-summary";
import PipelineHistory from "../components/pipeline-history";
import { validatePackageFiles } from "../lib/validation";
import {
  buildMockResult,
  computeProgress,
  costIncurred,
  logsForStep,
  mockLogs,
  mockPipelineId,
  mockThinking,
  recomputePipeline,
  stepStatus,
  validateTask,
} from "../lib/pipeline";
import {
  exportPackage,
  fetchPipeline,
  fetchSkills as apiFetchSkills,
  readComposeStream,
  startComposeStream,
  validatePackageRemote,
} from "../lib/api";
import type {
  ComposeResponse,
  ExecutionLog,
  ExportedPackage,
  HistoryItem,
  Phase,
  Pipeline,
  Skill,
  Subtask,
  ThinkingStep,
  ValidationReport,
} from "../lib/types";


const HISTORY_KEY = "sf-history-v1";
const HISTORY_CAP = 30;

// History entries are append-ordered (oldest first; the panel renders newest
// first). Live entries are deduped by their Redis pipeline id so reopening the
// same share link doesn't stack duplicates, and the list is capped so the
// localStorage snapshot stays small.
function upsertHistory(list: HistoryItem[], entry: HistoryItem, cap = HISTORY_CAP): HistoryItem[] {
  if (entry.kind === "live" && entry.pipelineId) {
    const dup = list.findIndex(e => e.kind === "live" && e.pipelineId === entry.pipelineId);
    if (dup !== -1) {
      const next = [...list];
      next[dup] = entry;
      return next;
    }
  }
  const next = [...list, entry];
  return next.length > cap ? next.slice(next.length - cap) : next;
}

function loadHistory(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as HistoryItem[];
    if (!Array.isArray(parsed)) return [];
    // Tolerate entries persisted before the provenance fields existed.
    return parsed.map(e => ({
      ...e,
      kind: e.kind === "live" ? "live" : "mock",
      pipelineId: typeof e.pipelineId === "string" ? e.pipelineId : undefined,
    }));
  } catch {
    return [];
  }
}


export default function Home() {
  const [task, setTask] = useState("");
  const [robot, setRobot] = useState("unitree-g1");
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<ComposeResponse | null>(null);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState("");
  const [lastComposed, setLastComposed] = useState<{ task: string; robot: string } | null>(null);
  const [activeTab, setActiveTab] = useState<"analysis" | "json" | "thinking" | "logs">("analysis");
  const [copied, setCopied] = useState(false);
  const [mockMode, setMockMode] = useState(true);
  // SSR renders dark; the layout bootstrap script already set <html data-theme>
  // before hydration, so the adopt effect below syncs state with zero flash.
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const themeTouched = useRef(false);

  // Keep <html data-theme> in sync with React state (CSS token override).
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Adopt the resolved theme after mount. The first render is SSR-dark (no
  // hydration mismatch); this effect then syncs state with the theme the
  // bootstrap script chose (explicit choice, else OS preference).
  useEffect(() => {
    let boot: "dark" | "light" = "dark";
    try {
      const t = localStorage.getItem("sf-theme");
      boot =
        t === "dark" || t === "light"
          ? t
          : window.matchMedia("(prefers-color-scheme: light)").matches
            ? "light"
            : "dark";
    } catch { /* storage unavailable */ }
    setTheme(boot);
  }, []);

  const toggleTheme = () => {
    themeTouched.current = true;
    const next: "dark" | "light" = theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("sf-theme", next); } catch { /* storage unavailable */ }
    const el = document.documentElement;
    el.classList.add("theme-transition");
    window.setTimeout(() => el.classList.remove("theme-transition"), 450);
    setTheme(next);
  };
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillPanelOpen, setSkillPanelOpen] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [expandedHistory, setExpandedHistory] = useState<Set<string>>(new Set());
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [exportedPkg, setExportedPkg] = useState<ExportedPackage | null>(null);
  const [exporting, setExporting] = useState(false);
  const [pipelineId, setPipelineId] = useState("");
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null);
  const [validating, setValidating] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  // Human editing of the pipeline: `draft` is the working copy while edit mode
  // is on; `edited` means the displayed pipeline differs from the stored
  // pipeline_id (a re-export is required to publish a new share link).
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState<Pipeline | null>(null);
  const [edited, setEdited] = useState(false);
  // "Create variation": compose a NEW pipeline adapted from the displayed one.
  const [variationOpen, setVariationOpen] = useState(false);
  const [variationTask, setVariationTask] = useState("");
  const [variationRobot, setVariationRobot] = useState("unitree-g1");
  // Fires the compose once the reworded task/robot have committed to state
  // (the compose handlers read state synchronously, so firing them straight
  // from the submit handler would compose the PREVIOUS task).
  const [pendingVariation, setPendingVariation] = useState<{ seed: Pipeline | null } | null>(null);

  const inputRef = useRef<HTMLDivElement>(null);
  const processingRef = useRef<HTMLDivElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const variationRef = useRef<HTMLDivElement>(null);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, []);

  // Fetch the skill catalog from the API (empty list shows the retry hint).
  const fetchSkills = useCallback(async () => {
    setSkillsLoading(true);
    try {
      setSkills(await apiFetchSkills());
    } catch {
      // Backend unreachable — the skill panel offers a retry button.
    } finally {
      setSkillsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (skillPanelOpen && skills.length === 0) {
      fetchSkills();
    }
  }, [skillPanelOpen, skills.length, fetchSkills]);

  // Restore a shared pipeline from the URL hash (e.g. /#p=paba41a1eac).
  // The pipeline is fetched from the backend session store by id.
  useEffect(() => {
    const match = window.location.hash.match(/^#p=([A-Za-z0-9_-]+)$/);
    if (!match) return;
    const id = match[1];
    fetchPipeline(id)
      .then(p => {
        const explanation = (p as { explanation?: string }).explanation || "";
        const sharedResult: ComposeResponse = { pipeline: p, explanation };
        setPipelineId(id);
        setTask(p.task || "");
        setRobot(p.robot || "unitree-g1");
        setResult(sharedResult);
        setPhase("results");
        setLastComposed({ task: p.task || "", robot: p.robot || "unitree-g1" });
        setHistory(prev => upsertHistory(prev, { id: `h-${Date.now()}`, task: p.task || "", robot: p.robot || "unitree-g1", kind: "live", pipelineId: id, result: sharedResult, timestamp: Date.now() }));
        scrollTo(resultsRef, 300);
      })
      .catch(() => {
        setError("pipeline not found — the session store may have expired. compose the task again.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist pipeline history locally so composed pipelines survive reloads.
  // Mock pipelines have no server copy (this snapshot is the only record);
  // live pipelines keep their Redis id and are refreshed on reopen.
  const historyLoaded = useRef(false);
  useEffect(() => {
    setHistory(loadHistory());
    historyLoaded.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!historyLoaded.current) return;
    try {
      const trimmed = history.length > HISTORY_CAP ? history.slice(history.length - HISTORY_CAP) : history;
      localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
    } catch { /* storage unavailable or quota exceeded */ }
  }, [history]);

  // Run a submitted variation compose (handlers declared below are read at
  // effect time, after this render's task/robot states are in place).
  useEffect(() => {
    if (!pendingVariation) return;
    const { seed } = pendingVariation;
    setPendingVariation(null);
    if (mockMode) handleComposeMock(seed);
    else handleComposeLive(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingVariation]);

  const getMockData = (): ComposeResponse => buildMockResult(task, robot);
  const getMockThinking = (): ThinkingStep[] => mockThinking(robot);
  const getMockLogs = (): ExecutionLog[] => mockLogs(task, robot);

  const getProgress = () => computeProgress(executionLogs);

  const getStepStatus = (stepNum: number): "completed" | "running" | "pending" =>
    stepStatus(executionLogs, stepNum);

  const getStepLogs = (stepNum: number) => logsForStep(executionLogs, stepNum);

  const getCumulativeCost = () =>
    costIncurred(executionLogs, result?.pipeline || getMockData().pipeline);

  const toggleStep = (stepNum: number) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(stepNum)) next.delete(stepNum);
      else next.add(stepNum);
      return next;
    });
  };

  const scrollTo = useCallback((ref: React.RefObject<HTMLDivElement | null>, delay = 150) => {
    setTimeout(() => {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, delay);
  }, []);

  const resetState = () => {
    setResult(null);
    setError("");
    setThinkingSteps([]);
    setExecutionLogs([]);
    setExpandedSteps(new Set());
    setActiveTab("analysis");
    setPipelineId("");
    setValidationReport(null);
    setEditMode(false);
    setDraft(null);
    setEdited(false);
    setVariationOpen(false);
  };


  const handleComposeMock = async (_seed?: Pipeline | null) => {
    const v = validateTask(task);
    if (v) { setValidation(v); return; }
    setValidation("");
    resetState();
    setPhase("processing");
    setLastComposed({ task, robot });
    scrollTo(processingRef, 200);

    const mockThinking = getMockThinking();
    for (let i = 0; i < mockThinking.length; i++) {
      await new Promise(r => setTimeout(r, 300));
      setThinkingSteps(prev => [...prev, mockThinking[i]]);
    }

    await new Promise(r => setTimeout(r, 400));

    const mockLogs = getMockLogs();
    for (let i = 0; i < mockLogs.length; i++) {
      await new Promise(r => setTimeout(r, 400));
      setExecutionLogs(prev => [...prev, mockLogs[i]]);
    }

    const mockResult = getMockData();
    setPipelineId(mockPipelineId(robot));
    setResult(mockResult);
    setPhase("results");
    setHistory(prev => upsertHistory(prev, { id: `h-${Date.now()}`, task, robot, kind: "mock", result: mockResult, timestamp: Date.now() }));
    scrollTo(resultsRef, 300);
  };

  const handleComposeLive = async (seed?: Pipeline | null) => {
    const v = validateTask(task);
    if (v) { setValidation(v); return; }
    setValidation("");
    resetState();
    setPhase("processing");
    setLastComposed({ task, robot });
    scrollTo(processingRef, 200);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);

    try {
      const res = await startComposeStream(task, robot, controller.signal, seed ?? null);
      clearTimeout(timeout);

      if (res.status === 429) throw new Error("rate limited — nebium api quota exceeded, try again in a few minutes");
      if (res.status === 503) throw new Error("service unavailable — backend is starting up, wait a moment and retry");
      if (res.status === 404) throw new Error("endpoint not found — is the backend server running? (cd agent && python server.py)");
      if (!res.ok) throw new Error(`api error (${res.status}) — ${res.statusText || "unknown error"}`);

      const final = await readComposeStream(res, {
        onThinking: step => setThinkingSteps(prev => [...prev, { ...step, timestamp: Date.now() }]),
        onPipeline: (pipeline, id) => {
          setPipelineId(id);
          setResult({ pipeline, explanation: "" });
        },
        onExplanation: text => setResult(prev => (prev ? { ...prev, explanation: text } : prev)),
        onLog: log => setExecutionLogs(prev => [...prev, { ...log, timestamp: Date.now() }]),
      });

      // Adopt the streamed result: pipeline id, shareable URL hash, history.
      setPipelineId(final.pipelineId);
      window.history.replaceState(null, "", `#p=${final.pipelineId}`);
      setResult(final);
      setPhase("results");
      setHistory(prev => upsertHistory(prev, { id: `h-${Date.now()}`, task, robot, kind: "live", pipelineId: final.pipelineId, result: final, timestamp: Date.now() }));
      scrollTo(resultsRef, 300);
    } catch (e) {
      clearTimeout(timeout);
      if (e instanceof Error && e.name === "AbortError") {
        setError("timeout — api took too long (>30s). try a simpler task or switch to mock mode.");
      } else {
        setError(e instanceof Error ? e.message : "unknown error — check console for details");
      }
      setPhase("idle");
    }
  };

  const handleCompose = mockMode ? handleComposeMock : handleComposeLive;

  // The pipeline actually displayed: the working draft during edit mode, else
  // the canonical result. Everything downstream (stats, timeline, json, export)
  // reads from here so edits are reflected everywhere.
  const displayPipeline = draft ?? result?.pipeline ?? null;

  const handleCopyJson = () => {
    if (!result) return;
    navigator.clipboard.writeText(JSON.stringify(displayPipeline ?? result.pipeline, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRetry = () => {
    if (lastComposed) {
      setTask(lastComposed.task);
      setRobot(lastComposed.robot);
      setError("");
      handleCompose();
    }
  };

  const handleNewCompose = () => {
    setPhase("idle");
    resetState();
    setValidation("");
    setTask("");
    setLastComposed(null);
    setExportedPkg(null);
    setLinkCopied(false);
    window.history.replaceState(null, "", window.location.pathname);
    scrollTo(inputRef, 100);
  };

  const handleShareLink = () => {
    if (!pipelineId) return;
    const url = `${window.location.origin}${window.location.pathname}#p=${pipelineId}`;
    navigator.clipboard.writeText(url);
    setLinkCopied(true);
    setTimeout(() => setLinkCopied(false), 2000);
  };

  const toggleCompareItem = (id: string) => {
    setCompareIds(prev => {
      if (prev.includes(id)) return prev.filter(i => i !== id);
      if (prev.length >= 3) return prev;
      return [...prev, id];
    });
  };

  const clearCompare = () => setCompareIds([]);

  const toggleHistoryItem = (id: string) => {
    setExpandedHistory(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Reopen a past pipeline from history: restore the results view (task,
  // robot, pipeline) so the user can tweak steps and re-export LLM-free.
  // Live entries are refreshed from the Redis store by id when possible;
  // expired/unreachable entries fall back to the stored snapshot so work is
  // never lost — the re-export path then publishes the inline pipeline under
  // a fresh id.
  const handleOpenHistory = async (item: HistoryItem) => {
    setError("");
    setValidation("");
    setExportedPkg(null);
    setLinkCopied(false);
    setValidationReport(null);
    setExpandedSteps(new Set());
    setThinkingSteps([]);
    setExecutionLogs([]);
    setActiveTab("analysis");
    setTask(item.task);
    setRobot(item.robot);
    setLastComposed({ task: item.task, robot: item.robot });

    let adopted = item.result;
    let pid = "";
    if (item.kind === "live" && item.pipelineId) {
      pid = item.pipelineId;
      try {
        const fresh = await fetchPipeline(item.pipelineId);
        adopted = { pipeline: fresh, explanation: (fresh as { explanation?: string }).explanation || item.result.explanation };
      } catch {
        // Redis copy expired (7-day TTL) or backend unreachable — keep the
        // stored snapshot; re-export publishes it under a fresh id.
        pid = "";
      }
    }

    setDraft(null);
    setEdited(false);
    setEditMode(false);
    setResult(adopted);
    setPipelineId(pid);
    setPhase("results");
    window.history.replaceState(null, "", pid ? `#p=${pid}` : window.location.pathname);
    scrollTo(resultsRef, 300);
  };

  // --- Create variation: reword the task / pick a robot, compose seeded ------
  const beginVariation = () => {
    const base = displayPipeline ?? result?.pipeline;
    if (!base) return;
    setVariationTask(base.task || "");
    setVariationRobot(base.robot || robot);
    setVariationOpen(true);
    scrollTo(variationRef, 80);
  };

  const cancelVariation = () => setVariationOpen(false);

  const submitVariation = () => {
    if (!variationTask.trim()) return;
    // Capture the original BEFORE the compose flow resets the result.
    const seed = displayPipeline ?? result?.pipeline ?? null;
    setVariationOpen(false);
    setTask(variationTask);
    setRobot(variationRobot);
    setPendingVariation({ seed });
  };

  // --- Pipeline editing: reorder / remove steps, then re-export LLM-free ------
  const beginEdit = () => {
    if (!result) return;
    setDraft(structuredClone(result.pipeline));
    setEditMode(true);
    setVariationOpen(false);
  };

  const doneEditing = () => {
    if (!draft) { setEditMode(false); return; }
    setResult(prev => (prev ? { ...prev, pipeline: draft } : prev));
    setEdited(true);
    setDraft(null);
    setEditMode(false);
  };

  const cancelEditing = () => {
    setDraft(null);
    setEditMode(false);
  };

  const renumberAndTotals = (subs: Subtask[]): Pipeline =>
    recomputePipeline(draft ?? result!.pipeline, subs);

  const moveStep = (index: number, dir: -1 | 1) => {
    if (!draft) return;
    const subs = [...draft.subtasks];
    const j = index + dir;
    if (j < 0 || j >= subs.length) return;
    [subs[index], subs[j]] = [subs[j], subs[index]];
    setDraft(renumberAndTotals(subs));
  };

  const removeStep = (index: number) => {
    if (!draft) return;
    const subs = draft.subtasks.filter((_, i) => i !== index);
    setDraft(renumberAndTotals(subs));
  };

  const handleExportRos2 = async () => {
    if (!result || exporting) return;
    setExporting(true);
    try {
      // Edited pipelines must NOT carry the stale pipeline_id: the backend
      // resolves pipeline_id before the inline payload, so keeping it would
      // re-export the original. Omitting it forces the inline (edited) pipeline
      // to be stored and exported — no LLM call.
      // No valid server id (mock pipeline, or a live entry whose Redis copy
      // expired) means the inline pipeline is authoritative — sending a stale
      // pipeline_id would make the backend re-export the wrong original.
      const payload = edited || !pipelineId
        ? { task, robot, pipeline: displayPipeline ?? result.pipeline }
        : { task, robot, pipeline_id: pipelineId, pipeline: result.pipeline };
      const data = await exportPackage(payload);
      setValidationReport(null);
      setExportedPkg(data);
      // The exported pipeline is now canonical: adopt its id and the URL hash,
      // so the share link points at the edited content.
      if (data.pipeline_id) {
        setPipelineId(data.pipeline_id);
        window.history.replaceState(null, "", `#p=${data.pipeline_id}`);
      }
      if (displayPipeline) setResult(prev => (prev ? { ...prev, pipeline: displayPipeline } : prev));
      setEdited(false);
      setDraft(null);
      setEditMode(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "export failed");
    } finally {
      setExporting(false);
    }
  };

  const handleExportMock = () => {
    if (!result) return;
    const p = displayPipeline ?? result.pipeline;
    const robotSlug = robot.replace("unitree-", "").replace("1x-", "neo-");
    const pkgName = `sf_${robotSlug}_${p.task_type}`;
    setExportedPkg({
      package_name: pkgName,
      files: {
        "package.xml": `<?xml version="1.0"?>\n<package format="3">\n  <name>${pkgName}</name>\n  <version>1.0.0</version>\n  <description>SkillForge pipeline for ${robot}</description>\n  <maintainer email="noreply@skillforge.dev">SkillForge</maintainer>\n  <license>Apache-2.0</license>\n  <!-- NOTE: This package references NVIDIA tools (GR00T N1, SONIC, Cosmos, Isaac Sim)\n       which have their own licenses. See https://developer.nvidia.com/licenses -->\n  <buildtool_depend>ament_cmake</buildtool_depend>\n  <depend>rclcpp</depend>\n  <depend>std_msgs</depend>\n</package>`,
        "CMakeLists.txt": `cmake_minimum_required(VERSION 3.8)\nproject(${pkgName})\n\nfind_package(ament_cmake REQUIRED)\nfind_package(rclcpp REQUIRED)\n\nament_package()`,
        "pipeline.json": JSON.stringify({ pipeline: p, metadata: { generated_by: "SkillForge v0.1.0", license: "Apache-2.0 (pipeline structure) — NVIDIA tool licenses apply separately" } }, null, 2),
        "launch/pipeline.launch.py": `from launch import LaunchDescription\nfrom launch_ros.actions import Node\n\ndef generate_launch_description():\n    return LaunchDescription([\n        Node(package="${pkgName}", executable="pipeline_node", name="pipeline", output="screen")\n    ])\n`,
        "README.md": `# ${pkgName}\n\nAuto-generated by SkillForge.\n\n## License\n\nThis pipeline is licensed under Apache-2.0. However, it references NVIDIA tools\n(GR00T N1, SONIC, Cosmos, Isaac Sim) which have their own licenses.\nSee https://developer.nvidia.com/licenses for NVIDIA tool licensing.\n\n## Task\n${task}\n\n## Robot\n${robot}\n\n## Cost\n$${p.total_estimated_cost_usd.toFixed(2)}`,
      },
      metadata: { generated_by: "SkillForge v0.1.0", pipeline_hash: "mock", package_name: pkgName, license: "Apache-2.0 (pipeline structure) — NVIDIA tool licenses apply separately" },
    });
    setValidationReport(null);
    // The mock export is also a re-export: the edited pipeline is now the
    // packaged one, so the edited/publish flag clears.
    setEdited(false);
    setDraft(null);
    setEditMode(false);
  };

  const handleValidatePkg = async () => {
    if (!exportedPkg || validating) return;
    setValidating(true);
    try {
      if (mockMode) {
        // Small delay to mirror a network request, then run the same structural checks client-side.
        await new Promise(r => setTimeout(r, 400));
        setValidationReport(validatePackageFiles(exportedPkg.files));
      } else {
        setValidationReport(await validatePackageRemote(exportedPkg.files, exportedPkg.package_name));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "validation failed");
    } finally {
      setValidating(false);
    }
  };

  const robotLabel = ROBOT_OPTIONS.find((r) => r.value === robot);
  const progress = getProgress();
  const cumulativeCost = getCumulativeCost();

  const tabBtn = (tab: "analysis" | "json" | "thinking" | "logs", label: string, icon: string) => (
    <button
      onClick={() => setActiveTab(tab)}
      style={{
        background: activeTab === tab ? "var(--acc-soft-2)" : "none",
        border: "none",
        borderBottom: activeTab === tab ? "2px solid var(--acc)" : "2px solid transparent",
        padding: "10px 16px",
        color: activeTab === tab ? "var(--acc)" : "var(--text-mid)",
        fontSize: "11px",
        fontWeight: 600,
        cursor: "pointer",
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.5px",
        display: "flex",
        alignItems: "center",
        gap: "6px",
      }}
    >
      <span style={{ fontSize: "12px" }}>{icon}</span>
      {label}
    </button>
  );

  // Determine visibility classes based on phase
  const inputVisible = phase === "idle";
  const processingVisible = phase === "processing" || phase === "results";
  const resultsVisible = phase === "results";

  return (
    <>


      <div style={{ minHeight: "100vh", color: "var(--text-1)", fontFamily: "var(--font-sans)", overflowX: "hidden", display: "flex", flexDirection: "column" }}>
        {/* Header */}
        <header className="header-inner" style={{ padding: "16px 40px", borderBottom: "1px solid var(--line)", background: "linear-gradient(180deg, var(--surface-header) 0%, var(--bg) 100%)", display: "flex", alignItems: "center", gap: "12px", position: "sticky", top: 0, zIndex: 100 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "18px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>{">>>"}</span>
            <h1 style={{ fontSize: "18px", fontWeight: 700, color: "var(--acc)", margin: 0, fontFamily: "var(--font-mono)", letterSpacing: "-0.3px" }}>skillforge</h1>
          </div>
          <span style={{ fontSize: "11px", background: "var(--acc-fill)", color: "var(--inverse)", padding: "2px 8px", borderRadius: "3px", fontWeight: 700, letterSpacing: "0.5px", fontFamily: "var(--font-mono)" }}>NVIDIA</span>
          {/* Theme toggle — always visible (mock/live lives in the compose box) */}
          <button
            onClick={toggleTheme}
            title={theme === "dark" ? "switch to light theme" : "switch to dark theme"}
            aria-label={theme === "dark" ? "switch to light theme" : "switch to dark theme"}
            style={{
              background: "none",
              border: "1px solid var(--line)",
              borderRadius: "4px",
              padding: "3px 8px",
              color: "var(--text-dim)",
              fontSize: "10px",
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
              display: "flex",
              alignItems: "center",
              gap: "4px",
              transition: "all 0.2s ease",
              marginLeft: "auto",
            }}
          >
            <span style={{ fontSize: "11px", lineHeight: 1 }}>{theme === "dark" ? "☀" : "☾"}</span>
            {theme === "dark" ? "light" : "dark"}
          </button>
          {/* Skills button — hidden on mobile */}
          <div className="header-right" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              onClick={() => setSkillPanelOpen(!skillPanelOpen)}
              style={{
                background: skillPanelOpen ? "var(--acc-soft-2)" : "none",
                border: skillPanelOpen ? "1px solid var(--acc-line-hi)" : "1px solid var(--line)",
                borderRadius: "4px", padding: "3px 8px",
                color: skillPanelOpen ? "var(--acc)" : "var(--text-dim)",
                fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)",
                transition: "all 0.2s ease",
              }}
            >
              skills ({skills.length || "..."})
            </button>
            <span style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>nebius_token_factory</span>
          </div>
        </header>

        {/* Live mode banner */}
        {!mockMode && (
          <div style={{ background: "var(--warn-soft)", borderBottom: "1px solid var(--warn-line)", padding: "6px 16px", textAlign: "center" }}>
            <span style={{ fontSize: "10px", color: "var(--warn)", fontFamily: "var(--font-mono)" }}>⚠ live mode — API calls use your Nebius credits ($25 budget)
            </span>
          </div>
        )}

        <SkillPanel
          open={skillPanelOpen}
          skills={skills}
          loading={skillsLoading}
          onClose={() => setSkillPanelOpen(false)}
          onFetch={fetchSkills}
        />

        <main className="main-content" style={{ maxWidth: "900px", margin: "0 auto", padding: "48px 20px", flex: 1, width: "100%" }}>

          {/* ===== SECTION 1: INPUT ===== */}
          <div
            ref={inputRef}
            className={`phase-section ${inputVisible ? "phase-visible input-expanded" : "phase-hidden input-compressed"}`}
            style={{ transition: inputVisible ? "opacity 0.4s ease, transform 0.4s ease, max-height 0.5s ease" : "opacity 0.3s ease, transform 0.3s ease, max-height 0.4s ease" }}
          >

            {inputVisible && (
              /* Full input form */
              <div className="fade-in-up">
                <div style={{ textAlign: "center", marginBottom: "36px" }}>
                  <h2 className="hero-title" style={{ fontSize: "32px", fontWeight: 800, margin: "0 0 16px", letterSpacing: "-0.5px", color: "var(--text-hi)", lineHeight: 1.2 }}>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--acc)" }}>{">>>"}</span> Describe a task.
                  </h2>
                  <h2 className="hero-title" style={{ fontSize: "32px", fontWeight: 800, margin: "0 0 16px", letterSpacing: "-0.5px", color: "var(--text-hi)", lineHeight: 1.2 }}>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--acc)" }}>{">>>"}</span> Get a pipeline.
                  </h2>
                  <p style={{ fontSize: "13px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.2px" }}>// natural language in. nvidia skills out.</p>
                </div>

                {/* Compose mode: mock (free demo) vs live (real LLM + credits) */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", marginBottom: "20px" }}>
                  <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.5px" }}>// compose_mode</span>
                  <div style={{ display: "inline-flex", gap: "3px", background: "var(--bg-inset)", border: "1px solid var(--line)", borderRadius: "6px", padding: "2px" }}>
                    {(["mock", "live"] as const).map(m => {
                      const active = m === "mock" ? mockMode : !mockMode;
                      return (
                        <button
                          key={m}
                          data-mode={m}
                          aria-pressed={active}
                          title={m === "mock" ? "free demo — no backend or LLM calls" : "real API — composes with the live LLM and uses your Nebius credits"}
                          onClick={() => setMockMode(m === "mock")}
                          style={{
                            padding: "4px 12px",
                            borderRadius: "4px",
                            border: "none",
                            cursor: "pointer",
                            fontSize: "10px",
                            fontFamily: "var(--font-mono)",
                            letterSpacing: "0.5px",
                            fontWeight: 600,
                            background: active ? (m === "mock" ? "var(--acc-soft-2)" : "var(--warn-soft-2)") : "none",
                            color: active ? (m === "mock" ? "var(--acc)" : "var(--warn)") : "var(--text-dim)",
                          }}
                        >
                          {m}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div style={{ marginBottom: "20px" }}>
                  <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginBottom: "8px", letterSpacing: "0.5px" }}>// select_robot</div>
                  <div className="robot-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "10px" }}>
                    {ROBOT_OPTIONS.map((o) => (
                      <button
                        key={o.value}
                        onClick={() => setRobot(o.value)}
                        className="robot-card"
                        style={{
                          background: robot === o.value ? "var(--acc-soft)" : "var(--bg-card)",
                          border: robot === o.value ? "1px solid var(--acc)" : "1px solid var(--line)",
                          borderRadius: "6px", padding: "14px 12px", cursor: "pointer", textAlign: "center",
                        }}
                      >
                        <div className="robot-icon" style={{ fontSize: "24px", marginBottom: "6px" }}>{o.icon}</div>
                        <div style={{ fontSize: "12px", fontWeight: 700, color: robot === o.value ? "var(--acc)" : "var(--text-1)", marginBottom: "2px", fontFamily: "var(--font-mono)" }}>{o.label}</div>
                        <div style={{ fontSize: "10px", color: "var(--text-faint-2)", marginBottom: "4px" }}>{o.desc}</div>
                        <div style={{ fontSize: "10px", color: robot === o.value ? "var(--acc)" : "var(--text-faint)", padding: "2px 6px", borderRadius: "3px", display: "inline-block", fontFamily: "var(--font-mono)" }}>{o.type.toLowerCase()}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div style={{ marginBottom: "0" }}>
                  <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginBottom: "8px", letterSpacing: "0.5px" }}>// task_description</div>
                  <textarea
                    value={task}
                    onChange={(e) => { setTask(e.target.value); if (validation) setValidation(""); }}
                    placeholder="describe a robot task..."
                    style={{
                      width: "100%", height: "80px", background: "var(--bg-card)",
                      border: "1px solid var(--line)", borderRadius: "6px", padding: "14px",
                      color: "var(--text-1)", fontSize: "13px", resize: "none", boxSizing: "border-box",
                      lineHeight: 1.6, fontFamily: "var(--font-mono)",
                    }}
                  />
                  <div className="compose-row" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "10px" }}>
                    <div className="chips-row" style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                      {EXAMPLE_TASKS.map((ex, i) => (
                        <button
                          key={i}
                          onClick={() => setTask(ex)}
                          className="suggestion-chip"
                          style={{ background: "none", border: "1px solid var(--line)", borderRadius: "4px", padding: "4px 10px", color: "var(--text-dim)", fontSize: "10px", cursor: "pointer", whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}
                        >
                          {ex.length > 28 ? ex.slice(0, 28) + "..." : ex}
                        </button>
                      ))}
                    </div>
                    <button
                      onClick={() => handleCompose()}
                      disabled={!task.trim()}
                      className="glow-btn"
                      style={{
                        height: "34px", padding: "0 16px",
                        background: !task.trim() ? "var(--bg-disabled)" : "var(--acc-grad)",
                        color: !task.trim() ? "var(--text-dim)" : "var(--inverse)",
                        border: "none", borderRadius: "6px", fontSize: "11px",
                        boxShadow: task.trim()
                          ? "var(--btn-shadow)"
                          : "none",
                        fontWeight: 700, cursor: !task.trim() ? "not-allowed" : "pointer",
                        flexShrink: 0, marginLeft: "10px", fontFamily: "var(--font-mono)",
                        opacity: !task.trim() ? 0.5 : 1,
                      }}
                    >
                      compose
                    </button>
                  </div>
                  {validation && (
                    <div style={{ marginTop: "6px", fontSize: "10px", color: "var(--warn)", fontFamily: "var(--font-mono)" }} className="fade-in-up">
                      ⚠ {validation}
                    </div>
                  )}
                  {!task.trim() && !validation && (
                    <div style={{ marginTop: "6px", fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>
                      enter a task description to compose a pipeline
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* ===== CONNECTOR 1 ===== */}
          <div className={`connector ${processingVisible ? "connector-visible" : "connector-hidden"}`}>
            <div style={{ width: "1px", height: "40px", margin: "0 auto", background: "linear-gradient(180deg, var(--acc), transparent)", animation: processingVisible ? "connectorPulse 2s ease-in-out infinite" : "none" }} />
          </div>

          {/* ===== SECTION 2: PROCESSING ===== */}
          <div
            ref={processingRef}
            className={`phase-section ${processingVisible ? "phase-visible" : "phase-hidden"}`}
            style={{ transitionDelay: processingVisible ? "0.15s" : "0s" }}
          >
            {/* Compact task bar */}
            <div style={{ background: "var(--bg-card)", border: "1px solid var(--line)", borderRadius: "6px", padding: "12px 14px", marginBottom: "20px", display: "flex", alignItems: "center", gap: "10px" }}>
              <span style={{ fontSize: "14px" }}>{robotLabel?.icon}</span>
              <span style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>{robotLabel?.label}</span>
              <span style={{ color: "var(--text-faint)" }}>│</span>
              <span style={{ fontSize: "12px", color: "var(--text-2)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}>{`"${task}"`}</span>
              {phase === "processing" && (
                <span style={{ fontSize: "11px", color: "var(--warn)", fontFamily: "var(--font-mono)", animation: "pulse 1.5s ease-in-out infinite" }}>executing</span>
              )}
              {phase === "results" && (
                <span style={{ fontSize: "11px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>✓ complete</span>
              )}
            </div>

            {/* Thinking process — comes first */}
            {thinkingSteps.length > 0 && (
              <div style={{ marginBottom: "20px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", marginBottom: "8px", letterSpacing: "0.5px" }}>
                  reasoning [step {thinkingSteps.length}/{thinkingSteps[thinkingSteps.length - 1]?.total || thinkingSteps.length}]
                </div>
                <div style={{ background: "var(--bg-raised)", border: "1px solid var(--line)", borderRadius: "4px", padding: "10px 12px", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
                  {thinkingSteps.map((step, i) => (
                    <div key={i} className="thinking-step" style={{ display: "flex", alignItems: "flex-start", gap: "8px", marginBottom: "6px" }}>
                      <span style={{ color: "var(--text-faint)", flexShrink: 0 }}>$</span>
                      <span style={{ color: i === thinkingSteps.length - 1 ? "var(--acc)" : "var(--text-mid)" }}>{step.content}</span>
                      {i === thinkingSteps.length - 1 && phase === "processing" && <span className="cursor-blink" style={{ color: "var(--acc)" }}>_</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Reasoning-only status while thinking, before execution starts */}
            {thinkingSteps.length > 0 && executionLogs.length === 0 && phase === "processing" && (
              <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "8px 12px", background: "var(--bg-card)", border: "1px solid var(--line)", borderRadius: "4px", marginBottom: "20px" }}>
                <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--warn)", animation: "pulse 1.5s ease-in-out infinite" }} />
                <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>analyzing task and selecting skills...</span>
              </div>
            )}

            {/* Progress indicator — comes after thinking */}
            {progress.total > 0 && (
              <div style={{ marginBottom: "20px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <div style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)", letterSpacing: "0.5px" }}>[pipeline] progress</div>
                  <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                    {progress.completed}/{progress.total} ({Math.round(progress.percentage)}%)
                  </div>
                </div>
                <div style={{ height: "4px", background: "var(--line)", borderRadius: "2px", overflow: "hidden", marginBottom: "14px" }}>
                  <div className="progress-bar" style={{ height: "100%", background: "var(--acc)", borderRadius: "2px", width: `${progress.percentage}%`, transition: "width 0.3s ease" }} />
                </div>
                <div className="progress-dots" style={{ display: "flex", justifyContent: "space-between", marginBottom: "14px" }}>
                  {Array.from({ length: progress.total }, (_, i) => i + 1).map(stepNum => {
                    const status = getStepStatus(stepNum);
                    return (
                      <div key={stepNum} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px" }}>
                        <div className="progress-dot" style={{
                          width: "20px", height: "20px", borderRadius: "50%",
                          background: status === "completed" ? "var(--acc-fill)" : status === "running" ? "var(--warn)" : "var(--line)",
                          border: status === "running" ? "2px solid var(--warn)" : "1px solid var(--text-faint)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: "10px", fontWeight: 700,
                          color: status === "completed" || status === "running" ? "var(--inverse)" : "var(--text-dim)",
                          fontFamily: "var(--font-mono)",
                          animation: status === "running" ? "pulse 1.5s ease-in-out infinite" : "none",
                        }}>
                          {status === "completed" ? "✓" : stepNum}
                        </div>
                        <div style={{ fontSize: "10px", color: status === "running" ? "var(--warn)" : "var(--text-faint)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>
                          {status === "running" ? "run" : status === "completed" ? "ok" : "wait"}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 10px", background: "var(--bg-card)", borderRadius: "4px", border: "1px solid var(--line)" }}>
                  <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>cost_incurred</span>
                  <span style={{ fontSize: "12px", color: "var(--acc)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>${cumulativeCost.toFixed(2)}</span>
                </div>
              </div>
            )}

            {/* Execution log cards */}
            {executionLogs.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginBottom: "20px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", marginBottom: "6px", letterSpacing: "0.5px" }}>execution_log</div>
                {Array.from({ length: progress.total }, (_, i) => i + 1).map(stepNum => {
                  const status = getStepStatus(stepNum);
                  const stepLogs = getStepLogs(stepNum);
                  const isExpanded = expandedSteps.has(stepNum);
                  const pipeline = result?.pipeline || getMockData().pipeline;
                  const subtask = pipeline.subtasks[stepNum - 1];

                  return (
                    <div
                      key={stepNum}
                      className="step-card"
                      onClick={() => toggleStep(stepNum)}
                      style={{
                        background: "var(--bg-raised)",
                        border: `1px solid ${status === "running" ? "var(--warn-line)" : status === "completed" ? "var(--acc-line)" : "var(--line)"}`,
                        borderRadius: "4px", overflow: "hidden",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "10px 12px" }}>
                        <div style={{
                          width: "18px", height: "18px", borderRadius: "50%",
                          background: status === "completed" ? "var(--acc-fill)" : status === "running" ? "var(--warn)" : "var(--line)",
                          border: status === "running" ? "2px solid var(--warn)" : "1px solid var(--text-faint)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: "10px", fontWeight: 700,
                          color: status === "completed" || status === "running" ? "var(--inverse)" : "var(--text-dim)",
                          fontFamily: "var(--font-mono)", flexShrink: 0,
                        }}>
                          {status === "completed" ? "✓" : stepNum}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <span style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>{subtask?.name || `step-${stepNum}`}</span>
                            <span style={{
                              fontSize: "10px", padding: "1px 5px", borderRadius: "3px",
                              background: status === "running" ? "var(--warn-soft-2)" : status === "completed" ? "var(--acc-soft-2)" : "var(--line)",
                              color: status === "running" ? "var(--warn)" : status === "completed" ? "var(--acc)" : "var(--text-faint)",
                              fontFamily: "var(--font-mono)",
                            }}>
                              {status === "running" ? "running" : status === "completed" ? "done" : "pending"}
                            </span>
                          </div>
                          <div style={{ fontSize: "10px", color: "var(--text-faint-2)", marginTop: "2px" }}>{subtask?.description || ""}</div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
                          <span style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>${subtask?.estimated_cost_usd.toFixed(2) || "0.00"}</span>
                          <span style={{
                            fontSize: "10px", color: "var(--text-faint)",
                            transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                            transition: "transform 0.2s ease",
                          }}>{"▼"}</span>
                        </div>
                      </div>
                      {isExpanded && stepLogs.length > 0 && (
                        <div style={{ borderTop: "1px solid var(--line)", padding: "10px 12px", background: "var(--bg-inset)" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: "4px", fontFamily: "var(--font-mono)", fontSize: "10px" }}>
                            {stepLogs.map((log, i) => (
                              <div key={i} className="log-entry" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <span style={{ color: log.status === "completed" ? "var(--acc)" : log.status === "failed" ? "var(--danger)" : "var(--warn)", fontSize: "8px" }}>
                                  {log.status === "completed" ? "●" : log.status === "failed" ? "✗" : "○"}
                                </span>
                                <span style={{ color: "var(--text-2)" }}>{log.content}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* ===== CONNECTOR 2 ===== */}
          <div className={`connector ${resultsVisible ? "connector-visible" : "connector-hidden"}`}>
            <div style={{ width: "1px", height: "40px", margin: "0 auto", background: "linear-gradient(180deg, var(--acc), transparent)", animation: resultsVisible ? "connectorPulse 2s ease-in-out infinite" : "none" }} />
          </div>

          {/* ===== SECTION 3: RESULTS ===== */}
          <div
            ref={resultsRef}
            className={`phase-section ${resultsVisible ? "phase-visible" : "phase-hidden"}`}
            style={{ transitionDelay: resultsVisible ? "0.3s" : "0s" }}
          >
            {result && (
              <>
                {/* Stats */}
                <div className="stats-grid fade-in-up" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "10px", marginBottom: "20px" }}>
                  <StatBlock label="steps" value={String(displayPipeline!.subtasks.length)} hint="How many stages the plan is split into" />
                  <StatBlock label="cost" value={`$${displayPipeline!.total_estimated_cost_usd.toFixed(2)}`} color="var(--acc)" hint="Estimated cost of the cloud computing needed to run this plan once" />
                  <StatBlock label="risk" value={result.pipeline.risk_assessment} color={result.pipeline.risk_assessment === "low" ? "var(--acc)" : "var(--warn)"} hint={result.pipeline.risk_assessment === "low" ? "Low risk — a simple, well-understood environment" : "Medium risk — real-world settings vary, so the plan may need adjustments"} />
                </div>

                {/* Plain-language explanation of the plan */}
                <PlainSummary pipeline={displayPipeline!} />

                {/* Variation composer — seeds a new compose from the displayed plan */}
                {variationOpen && (
                  <div
                    ref={variationRef}
                    className="fade-in-up"
                    style={{ marginBottom: "14px", background: "var(--bg-card)", border: "1px solid var(--acc-line)", borderRadius: "6px", padding: "14px" }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
                      <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--acc)", fontFamily: "var(--font-mono)" }}>🧬 create variation</span>
                      <button
                        onClick={cancelVariation}
                        title="close variation composer"
                        style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "1px 8px", color: "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
                      >✕</button>
                    </div>
                    <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginBottom: "8px" }}>
                      {mockMode
                        ? "composes from this robot's demo data — reword the task or switch robots"
                        : "the real LLM adapts the plan below — steps that still apply are kept, the rest are reworked"}
                    </div>
                    <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginBottom: "6px", letterSpacing: "0.5px" }}>// reword_the_task</div>
                    <textarea
                      data-testid="variation-task"
                      value={variationTask}
                      onChange={(e) => setVariationTask(e.target.value)}
                      rows={2}
                      placeholder="reword the task for this variation..."
                      style={{ width: "100%", boxSizing: "border-box", background: "var(--bg-inset)", border: "1px solid var(--line)", borderRadius: "4px", padding: "8px 10px", color: "var(--text-1)", fontSize: "12px", fontFamily: "var(--font-mono)", resize: "vertical", marginBottom: "10px" }}
                    />
                    <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginBottom: "6px", letterSpacing: "0.5px" }}>// variation_robot</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px", marginBottom: "12px" }}>
                      {ROBOT_OPTIONS.map(ro => {
                        const active = ro.value === variationRobot;
                        return (
                          <button
                            key={ro.value}
                            data-testid={`variation-robot-${ro.value}`}
                            onClick={() => setVariationRobot(ro.value)}
                            title={`${ro.desc} — ${ro.type}`}
                            style={{
                              display: "flex", alignItems: "center", gap: "6px", padding: "6px 10px", cursor: "pointer",
                              background: active ? "var(--acc-soft-2)" : "none",
                              border: active ? "1px solid var(--acc-line-hi)" : "1px solid var(--line)",
                              borderRadius: "4px", fontFamily: "var(--font-mono)", fontSize: "10px",
                              color: active ? "var(--acc)" : "var(--text-2)",
                            }}
                          >
                            <span style={{ fontSize: "13px" }}>{ro.icon}</span>
                            {ro.label}
                          </button>
                        );
                      })}
                    </div>
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
                      <button onClick={cancelVariation} style={{ background: "none", border: "1px solid var(--line)", borderRadius: "4px", padding: "5px 12px", color: "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}>
                        cancel
                      </button>
                      <button
                        onClick={submitVariation}
                        disabled={!variationTask.trim()}
                        className="glow-btn"
                        style={{
                          background: !variationTask.trim() ? "var(--bg-disabled)" : "var(--acc-grad)",
                          color: !variationTask.trim() ? "var(--text-dim)" : "var(--inverse)",
                          border: "none", borderRadius: "4px", padding: "5px 14px", fontSize: "10px", fontWeight: 700,
                          fontFamily: "var(--font-mono)", cursor: !variationTask.trim() ? "not-allowed" : "pointer",
                          boxShadow: variationTask.trim() ? "var(--btn-shadow)" : "none", opacity: !variationTask.trim() ? 0.5 : 1,
                        }}
                      >
                        compose variation
                      </button>
                    </div>
                  </div>
                )}

                {/* Timeline (with human edit controls) */}
                <PipelineTimeline
                  pipeline={displayPipeline!}
                  editMode={editMode}
                  onBeginEdit={beginEdit}
                  onBeginVariation={beginVariation}
                  onDoneEdit={doneEditing}
                  onCancelEdit={cancelEditing}
                  onMoveStep={moveStep}
                  onRemoveStep={removeStep}
                />

                {/* Tabs */}
                <div className="fade-in-up" style={{ animationDelay: "0.2s" }}>
                  <div className="tabs-scroll" style={{ display: "flex", borderBottom: "1px solid var(--line)" }}>
                    {tabBtn("analysis", "analysis", "ℹ")}
                    {tabBtn("thinking", "reasoning", "🧠")}
                    {tabBtn("logs", "logs", "📋")}
                    {tabBtn("json", "json", "{ }")}
                  </div>
                  <div style={{ background: "var(--bg-raised)", border: "1px solid var(--line)", borderTop: "none", borderRadius: "0 0 4px 4px", padding: "14px", marginBottom: "20px" }}>
                    {activeTab === "analysis" && result.explanation && (
                      <div className="overflow-safe" style={{ fontSize: "12px", color: "var(--text-2)", lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{result.explanation}</div>
                    )}
                    {activeTab === "analysis" && !result.explanation && (
                      <div style={{ fontSize: "12px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>// no analysis available</div>
                    )}
                    {activeTab === "thinking" && (
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}>
                        {thinkingSteps.length === 0 && <div style={{ color: "var(--text-faint)" }}>// no reasoning data</div>}
                        {thinkingSteps.map((step, i) => (
                          <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: "8px", padding: "8px 10px", background: "var(--bg-inset)", borderRadius: "4px", marginBottom: "4px" }}>
                            <span style={{ color: "var(--text-faint)", flexShrink: 0 }}>$</span>
                            <span style={{ color: "var(--text-2)" }}>{step.content}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {activeTab === "logs" && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px", fontFamily: "var(--font-mono)", fontSize: "10px" }}>
                        {executionLogs.length === 0 && <div style={{ color: "var(--text-faint)" }}>// no execution logs</div>}
                        {executionLogs.map((log, i) => (
                          <div key={i} style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px 8px", background: "var(--bg-inset)", borderRadius: "3px" }}>
                            <span style={{ color: log.status === "completed" ? "var(--acc)" : log.status === "failed" ? "var(--danger)" : "var(--warn)", fontSize: "8px" }}>
                              {log.status === "completed" ? "●" : log.status === "failed" ? "✗" : "○"}
                            </span>
                            <span style={{ color: "var(--text-faint)" }}>[{log.skill_id}]</span>
                            <span style={{ color: "var(--text-2)" }}>{log.content}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {activeTab === "json" && (
                      <div>
                        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "8px" }}>
                          <button onClick={handleCopyJson} style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "3px 10px", color: copied ? "var(--acc)" : "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}>
                            {copied ? "copied" : "copy"}
                          </button>
                        </div>
                        <pre style={{ fontSize: "10px", color: "var(--acc)", overflow: "auto", background: "var(--bg-inset)", padding: "12px", borderRadius: "4px", border: "1px solid var(--line)", margin: 0, fontFamily: "var(--font-mono)" }}>{JSON.stringify(displayPipeline ?? result.pipeline, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                </div>

                {/* Pipeline metadata */}
                <div className="fade-in-up" style={{ animationDelay: "0.25s", background: "var(--bg-raised)", border: "1px solid var(--line)", borderRadius: "4px", padding: "14px", marginBottom: "20px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                    <div style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", letterSpacing: "0.5px" }}>pipeline_metadata</div>
                    {edited ? (
                      <span style={{ fontSize: "10px", color: "var(--warn)", fontFamily: "var(--font-mono)" }}>edited — re-export to publish a new link</span>
                    ) : pipelineId.startsWith("p") && (
                      <button
                        onClick={handleShareLink}
                        style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "2px 8px", color: linkCopied ? "var(--acc)" : "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
                      >
                        {linkCopied ? "link copied" : "share link"}
                      </button>
                    )}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "8px" }}>
                    <MetaItem label="pipeline_id" value={pipelineId || `sf-${robot.replace("unitree-", "").replace("1x-", "neo-")}-${Date.now().toString(36).slice(-6)}`} hint="The shareable id behind the #p=... link — it reopens this exact plan" />
                    <MetaItem label="estimated_vram" value={displayPipeline!.subtasks.filter(s => s.gpu_required).length > 3 ? "16GB+" : "8GB"} hint="Graphics-card memory the robot's AI models need" />
                    <MetaItem label="framework" value="ROS2 Humble" hint="The standard robotics software framework this package is built for" />
                    <MetaItem label="sim_env" value="Isaac Sim 4.5" hint="NVIDIA's 3D simulator where the plan is trained and tested" />
                    <MetaItem label="export_format" value="ROS2 Package" hint="A ready-to-install software package for the robot" />
                    <MetaItem label="target_hw" value={robotLabel?.label || robot} hint="The robot this plan was composed for" />
                  </div>
                </div>

                {/* Export / Distribution */}
                <div className="fade-in-up" style={{ animationDelay: "0.3s", background: "var(--bg-raised)", border: "1px solid var(--line)", borderRadius: "4px", padding: "14px", marginBottom: "20px" }}>
                  <div style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", marginBottom: "10px", letterSpacing: "0.5px" }}>export_distribution</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <ExportOption
                      icon="📦"
                      label="ROS2 Package"
                      desc="Standard robot deployment — colcon build & run"
                      command={`colcon build --packages-select sf_${robot.replace("unitree-", "").replace("1x-", "neo-")}_pipeline`}
                    />
                    <ExportOption
                      icon="🐳"
                      label="Docker Container"
                      desc="Isolated environment with all dependencies"
                      command="docker pull skillforge/pipeline:sf-latest"
                    />
                    <ExportOption
                      icon="🎮"
                      label="Omniverse Scene"
                      desc="Open in Isaac Sim for visualization & testing"
                      command="isaacsim --open sf_pipeline.usd"
                    />
                    <div
                      onClick={(!exportedPkg || edited) ? (mockMode ? handleExportMock : handleExportRos2) : undefined}
                      style={{
                        padding: "10px 12px", background: "var(--bg-inset)",
                        borderRadius: "4px",
                        border: edited ? "1px solid var(--warn-line-hi)" : exportedPkg ? "1px solid var(--acc-line-hi)" : "1px solid var(--line)",
                        cursor: (exportedPkg && !edited) ? "default" : exporting ? "wait" : "pointer",
                        transition: "all 0.15s ease",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <span style={{ fontSize: "16px", flexShrink: 0 }}>{edited ? "✏️" : exportedPkg ? "✅" : "📄"}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: "11px", fontWeight: 600, color: edited ? "var(--warn)" : exportedPkg ? "var(--acc)" : "var(--text-1)", fontFamily: "var(--font-mono)" }}>
                            {exporting ? "generating..." : edited ? "re-export edited pipeline" : exportedPkg ? "package ready" : "Generate ROS2 Package"}
                          </div>
                          <div style={{ fontSize: "9px", color: "var(--text-faint-2)", marginTop: "2px" }}>
                            {exportedPkg ? exportedPkg.package_name : "Full ROS2 package with package.xml, CMakeLists, launch files"}
                          </div>
                        </div>
                        {!exportedPkg && !exporting && !edited && (
                          <span style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>click to generate</span>
                        )}
                        {edited && !exporting && (
                          <span style={{ fontSize: "10px", color: "var(--warn)", fontFamily: "var(--font-mono)" }}>LLM-free re-export</span>
                        )}
                        {exporting && (
                          <span style={{ fontSize: "10px", color: "var(--warn)", fontFamily: "var(--font-mono)", animation: "pulse 1.5s ease-in-out infinite" }}>generating...</span>
                        )}
                      </div>

                      {/* Generated files — shown inside the block after generation */}
                      {exportedPkg && (
                        <div style={{ marginTop: "10px", borderTop: "1px solid var(--line)", paddingTop: "10px" }}>
                          <div style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", marginBottom: "6px", letterSpacing: "0.5px" }}>files — click to copy</div>
                          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                            {Object.entries(exportedPkg.files).map(([filename, content]) => (
                              <ExportedFile key={filename} filename={filename} content={content} />
                            ))}
                          </div>

                          {/* Validate package */}
                          <div
                            onClick={validating ? undefined : handleValidatePkg}
                            style={{
                              marginTop: "10px", padding: "10px 12px", background: "var(--bg-inset)", borderRadius: "4px",
                              border: validationReport ? (validationReport.valid ? "1px solid var(--acc-line-hi)" : "1px solid var(--danger-line)") : "1px solid var(--line)",
                              cursor: validating ? "wait" : "pointer", transition: "all 0.15s ease",
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                              <span style={{ fontSize: "16px", flexShrink: 0 }}>
                                {validating ? "⏳" : validationReport ? (validationReport.valid ? "✅" : "⚠️") : "🧪"}
                              </span>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: "11px", fontWeight: 600, color: validating ? "var(--warn)" : validationReport ? (validationReport.valid ? "var(--acc)" : "var(--danger)") : "var(--text-1)", fontFamily: "var(--font-mono)" }}>
                                  {validating ? "validating..." : validationReport ? (validationReport.valid ? `package valid — ${validationReport.score}/100` : `package invalid — ${validationReport.score}/100`) : "Validate Package"}
                                </div>
                                <div style={{ fontSize: "9px", color: "var(--text-faint-2)", marginTop: "2px" }}>
                                  {validationReport ? `${validationReport.errors.length} errors, ${validationReport.warnings.length} warnings` : "Checks XML, cmake, python and JSON syntax"}
                                </div>
                              </div>
                              {!validating && (
                                <span style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>
                                  {validationReport ? "click to re-validate" : "click to validate"}
                                </span>
                              )}
                            </div>
                            {validationReport && (
                              <div style={{ marginTop: "10px", borderTop: "1px solid var(--line)", paddingTop: "8px", display: "flex", flexDirection: "column", gap: "4px", fontFamily: "var(--font-mono)", fontSize: "10px" }}>
                                {validationReport.errors.map((w, i) => (
                                  <div key={`e-${i}`} style={{ color: "var(--danger)" }}>✗ [{w.file}] {w.message}</div>
                                ))}
                                {validationReport.warnings.map((w, i) => (
                                  <div key={`w-${i}`} style={{ color: "var(--warn)" }}>△ [{w.file}] {w.message}</div>
                                ))}
                                {validationReport.errors.length === 0 && validationReport.warnings.length === 0 && validationReport.info.map((inf, i) => (
                                  <div key={`i-${i}`} style={{ color: "var(--text-dim)" }}>✓ [{inf.file}] {inf.message}</div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Timing info */}
                <div className="fade-in-up" style={{ animationDelay: "0.35s", padding: "10px 14px", background: "var(--bg-card)", border: "1px solid var(--line)", borderRadius: "4px", marginBottom: "20px", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>⚡</span>
                  <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                    pipeline generated in ~{(mockMode ? 8 : 12)}s{mockMode ? " (mock)" : " (live api)"} — {displayPipeline!.subtasks.length} steps — ${displayPipeline!.total_estimated_cost_usd.toFixed(2)} estimated
                  </span>
                </div>

                {/* Compose another */}
                <div style={{ textAlign: "center", animationDelay: "0.4s" }} className="fade-in-up">
                  <button
                    onClick={handleNewCompose}
                    style={{ background: "none", border: "none", color: "var(--text-faint)", fontSize: "11px", cursor: "pointer", padding: "8px 16px", fontFamily: "var(--font-mono)" }}
                    onMouseEnter={(e) => { e.currentTarget.style.color = "var(--acc)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = "var(--text-faint)"; }}
                  >
                    {">>> compose another"}
                  </button>
                </div>
              </>
            )}
          </div>

          {/* Error */}
          {error && (
            <div style={{ background: "var(--danger-soft)", border: "1px solid var(--danger-line)", borderRadius: "6px", padding: "12px 14px", marginBottom: "20px", color: "var(--danger)", fontSize: "12px", fontFamily: "var(--font-mono)" }} className="fade-in-up">
              <div style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                <span style={{ flexShrink: 0, marginTop: "1px" }}>✗</span>
                <span style={{ flex: 1, lineHeight: 1.5 }}>{error}</span>
              </div>
              <div style={{ display: "flex", gap: "8px", marginTop: "10px" }}>
                <button
                  onClick={handleRetry}
                  style={{ background: "var(--danger-soft-2)", border: "1px solid var(--danger-line)", borderRadius: "4px", padding: "4px 12px", color: "var(--danger)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
                >
                  retry
                </button>
                <button
                  onClick={() => { setError(""); setPhase("idle"); }}
                  style={{ background: "none", border: "1px solid var(--line)", borderRadius: "4px", padding: "4px 12px", color: "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
                >
                  dismiss
                </button>
              </div>
            </div>
          )}

          {/* Pipeline History */}
          {history.length > 0 && phase !== "processing" && (
            <PipelineHistory
              history={history}
              compareIds={compareIds}
              expandedHistory={expandedHistory}
              onToggleCompare={toggleCompareItem}
              onClearCompare={clearCompare}
              onToggleExpand={toggleHistoryItem}
              onOpen={handleOpenHistory}
            />
          )}

        </main>

        <footer style={{ marginTop: "auto", padding: "20px 0", borderTop: "1px solid var(--line)", textAlign: "center", color: "var(--text-faint)", fontSize: "10px", fontFamily: "var(--font-mono)" }}>
          skillforge pre-v0.1.0 // nebius global ai hackathon 2026
        </footer>
      </div>
    </>
  );
}
