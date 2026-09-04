"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { DryRunRecord, Pipeline } from "../lib/types";
import type { DryRunStep } from "../lib/dryrun";
import { fmtReplay, planDryRun } from "../lib/dryrun";

type RunStatus = "running" | "paused" | "done";

interface SimulationPanelProps {
  pipeline: Pipeline;
  robot: string;
  seed: number;
  /** Stored verdict of a previous run of this pipeline: when it is still
   *  consistent with the current plan (same steps, same seed), the panel
   *  renders it instantly instead of replaying. */
  initialResult?: DryRunRecord | null;
  /** Fired once per completed run so the page can persist the verdict. */
  onResult: (r: DryRunRecord) => void;
  onClose: () => void;
  onNewScenario: () => void;
}

const chip = (fg: string, bg: string, border: string): CSSProperties => ({
  fontSize: "10px", fontWeight: 700, fontFamily: "var(--font-mono)",
  padding: "1px 7px", borderRadius: "3px", color: fg, background: bg, border,
  letterSpacing: "0.5px", whiteSpace: "nowrap",
});

/** Replays a pipeline step-by-step with real pacing and simulated verdicts.
 *  Verdicts come from a deterministic seeded plan (lib/dryrun.ts): structural
 *  checks against skill metadata always fail the same way, seeded execution
 *  risk rerolls only when the user picks a "new scenario". */
export default function SimulationPanel({ pipeline, robot, seed, initialResult, onResult, onClose, onNewScenario }: SimulationPanelProps) {
  // A stored result pins the seed to the one the run actually used, so the
  // deterministic planner reproduces the identical scenario.
  const activeSeed = initialResult ? initialResult.seed : seed;
  const plan = useMemo(() => planDryRun(pipeline, robot, activeSeed), [pipeline, robot, activeSeed]);
  // The stored view is only valid while it matches the CURRENT plan: if the
  // pipeline was edited after the run (steps reordered/removed), the record
  // is stale and the panel must replay live rather than show a wrong verdict.
  const recordConsistent =
    initialResult != null &&
    plan.steps.length === initialResult.verdicts.length &&
    plan.steps.every((s, i) => s.verdict === initialResult!.verdicts[i]);
  const [status, setStatus] = useState<RunStatus>(initialResult && recordConsistent ? "done" : "running");
  const [elapsedMs, setElapsedMs] = useState(initialResult && recordConsistent ? initialResult.elapsedSec * 1000 : 0);
  const lastTickRef = useRef<number | null>(null);
  // True once the user pressed "↻ replay": after that the stored view is a
  // fresh run and the "last run" framing no longer applies.
  const replayedRef = useRef(false);
  const prevStatusRef = useRef<RunStatus>(status);

  const resetRun = () => { setElapsedMs(0); setStatus("running"); };

  // Auto-run on mount (fresh opens only — a stored verdict renders as-is)
  // and whenever the scenario seed changes.
  useEffect(() => {
    if (initialResult && recordConsistent) return;
    resetRun();
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [seed, plan, initialResult, recordConsistent]);

  // Report the completed run upward once, when the status flips running→done.
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    if (status === "done" && prev === "running") {
      onResult({
        seed: activeSeed,
        elapsedSec: Math.round((plan.haltMs / 1000) * 10) / 10,
        verdicts: plan.steps.map(s => s.verdict),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  // Advance a real wall-clock every 60ms while running; pausing stops the
  // clock, replaying re-arms it from zero.
  useEffect(() => {
    if (status !== "running") return;
    lastTickRef.current = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now();
      const prev = lastTickRef.current ?? now;
      lastTickRef.current = now;
      setElapsedMs(e => e + (now - prev));
    }, 60);
    return () => { window.clearInterval(id); lastTickRef.current = null; };
  }, [status]);

  // Completion: the run ends at the first failing step (or the whole replay).
  useEffect(() => {
    if (status !== "running") return;
    if (plan.steps.length === 0 || elapsedMs >= plan.haltMs) {
      setElapsedMs(plan.haltMs);
      setStatus("done");
    }
  }, [status, elapsedMs, plan.steps.length, plan.haltMs]);

  const finished = status === "done";
  const storedView = Boolean(initialResult) && recordConsistent && finished && !replayedRef.current;
  const displayMs = Math.min(elapsedMs, plan.haltMs);
  const displaySec = storedView ? initialResult!.elapsedSec : displayMs / 1000;

  const uiState = (s: DryRunStep): "pending" | "running" | "done" => {
    if (!s.structural) {
      if (elapsedMs < s.startMs) return "pending";
      if (elapsedMs >= s.endMs) return "done";
      return "running";
    }
    // Structural failures halt the sim the instant they are reached — there
    // is nothing to replay, so the row flips to done at its boundary.
    return elapsedMs >= s.startMs ? "done" : "pending";
  };

  const visibleLines = (s: DryRunStep): number => {
    const u = uiState(s);
    if (u === "pending") return 0;
    if (u === "done") return s.lines.length;
    const f = Math.min(1, (elapsedMs - s.startMs) / Math.max(1, s.durationMs));
    return Math.max(1, Math.min(s.lines.length, Math.floor(f * s.lines.length) + 1));
  };

  const progressPct = (s: DryRunStep): number => {
    const u = uiState(s);
    if (u === "pending") return 0;
    if (u === "done") return 100;
    return Math.min(100, Math.max(0, ((elapsedMs - s.startMs) / Math.max(1, s.durationMs)) * 100));
  };

  const activeStep = plan.steps.find(s => uiState(s) === "running") ?? null;
  const failStep = plan.firstFailIndex >= 0 ? plan.steps[plan.firstFailIndex] : null;
  const allPassed = plan.firstFailIndex === -1;

  const costIncurred = plan.steps
    .filter(s => !s.structural && s.endMs <= displayMs)
    .reduce((sum, s) => sum + s.costUsd, 0);

  // Stored view: the summary comes from the persisted record (faithful even
  // if the current plan would differ); pass counts come from its verdicts.
  const storedPassed =
    storedView && initialResult!.verdicts.every(v => v === "pass");
  const storedSummary =
    storedView && initialResult!.verdicts.length === 0
      ? "nothing to simulate — this pipeline has no steps"
      : storedView
        ? storedPassed
          ? `✓ dry-run passed — ${initialResult!.verdicts.filter(v => v === "pass").length}/${initialResult!.verdicts.length} steps passed (structural + simulated checks)`
          : (() => {
              const fi = plan.steps.findIndex(s => s.verdict === "fail");
              const fs = fi >= 0 ? plan.steps[fi] : null;
              return fs
                ? `✗ dry-run halted at step ${fs.order} ${fs.name} — ${fs.structural ? fs.preflight : fs.reason}`
                : "✗ dry-run halted — last run failed a simulated check";
            })()
        : null;

  const summary =
    plan.steps.length === 0
      ? "nothing to simulate — this pipeline has no steps"
      : storedSummary ?? (allPassed
        ? `✓ dry-run passed — ${plan.steps.length}/${plan.steps.length} steps passed (structural + simulated checks)`
        : `✗ dry-run halted at step ${failStep!.order} ${failStep!.name} — ${failStep!.structural ? failStep!.preflight : failStep!.reason}`);

  const runningLine = activeStep
    ? `replaying — step ${activeStep.order}/${plan.steps.length} · ${fmtReplay(displayMs)} elapsed`
    : `replaying — ${fmtReplay(displayMs)} elapsed`;

  const liveLine = status === "paused" ? `paused — ${runningLine.replace("replaying — ", "")}` : runningLine;

  return (
    <div
      data-testid="dryrun-panel"
      className="fade-in-up"
      style={{ background: "var(--bg-raised)", border: "1px solid var(--line)", borderRadius: "6px", padding: "14px", marginBottom: "20px" }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: "10px", marginBottom: "10px" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--acc)", fontFamily: "var(--font-mono)" }}>▶ simulation dry-run</span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", background: "var(--line)", padding: "1px 6px", borderRadius: "3px" }}>{plan.robotName}</span>
            <span data-testid="dryrun-seed" title="same plan + same seed = same outcome (deterministic)" style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", background: "var(--line)", padding: "1px 6px", borderRadius: "3px", cursor: "help" }}>
              seed 0x{plan.seed.toString(16).padStart(4, "0")}
            </span>
            <span style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>
              est. real run ~{plan.estimatedMinutes}m · replay ~{fmtReplay(plan.replayMs)} (compressed)
            </span>
          </div>
          <div style={{ fontSize: "10px", color: "var(--text-faint-2)", fontFamily: "var(--font-mono)", marginTop: "4px", lineHeight: 1.5 }}>
            simulated replay against skill metadata — not Isaac Sim. structural checks (anatomy, step order) always fail the same way; seeded execution risk rerolls on “new scenario”.
          </div>
        </div>
        <button
          onClick={onClose}
          title="close simulation dry-run"
          style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "1px 8px", color: "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)", flexShrink: 0 }}
        >✕</button>
      </div>

      {/* Whole-plan structural scan (instant, deterministic) */}
      <div
        data-testid="dryrun-preflight"
        style={{
          padding: "6px 10px", borderRadius: "4px", marginBottom: "10px",
          background: plan.issues.length ? "var(--warn-soft)" : "var(--bg-inset)",
          border: `1px solid ${plan.issues.length ? "var(--warn-line)" : "var(--line-soft)"}`,
          fontFamily: "var(--font-mono)", fontSize: "10px", color: plan.issues.length ? "var(--warn)" : "var(--text-dim)",
          lineHeight: 1.6,
        }}
      >
        {plan.issues.length === 0
          ? "preflight ok — 0 structural issues found. running the replay…"
          : (
            <div>
              <div>preflight — the plan can&apos;t run as ordered ({plan.issues.length} issue{plan.issues.length === 1 ? "" : "s"}):</div>
              {plan.issues.map(iss => (
                <div key={`${iss.order}-${iss.name}`} style={{ color: "var(--warn)", paddingLeft: "10px" }}>
                  · step {iss.order} &apos;{iss.name}&apos; — {iss.reason}
                </div>
              ))}
            </div>
          )}
      </div>

      {/* Steps */}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginBottom: "10px" }}>
        {plan.steps.length === 0 && (
          <div style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>// no steps in this pipeline</div>
        )}
        {plan.steps.map(s => {
          const u = uiState(s);
          const shown = visibleLines(s);
          const pct = progressPct(s);
          return (
            <div
              key={s.order}
              data-testid={`dryrun-step-${s.order}`}
              style={{
                background: "var(--bg-inset)",
                border: `1px solid ${u === "running" ? "var(--warn-line)" : u === "done" ? (s.verdict === "pass" ? "var(--acc-line)" : "var(--danger-line)") : "var(--line)"}`,
                borderRadius: "4px", padding: "8px 10px",
                opacity: u === "pending" ? 0.55 : 1,
                transition: "border-color 0.2s ease, opacity 0.2s ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>
                    <span style={{ color: "var(--text-faint-2)", marginRight: "5px" }}>{s.order}.</span>{s.name}
                    <span title={s.skillId} style={{ fontSize: "9px", color: "var(--text-faint)", marginLeft: "6px" }}>{s.skillId}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    <div style={{ flex: 1, maxWidth: "220px", height: "3px", background: "var(--bg-disabled)", borderRadius: "2px", overflow: "hidden" }}>
                      <div style={{ height: "100%", background: u === "done" ? (s.verdict === "pass" ? "var(--acc)" : "var(--danger)") : u === "running" ? "var(--warn)" : "var(--line)", borderRadius: "2px", width: `${pct}%`, transition: "width 0.12s linear" }} />
                    </div>
                    <span style={{ fontSize: "9px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", minWidth: "34px" }}>{u === "running" ? fmtReplay(displayMs - s.startMs) : u === "done" ? (s.structural ? "blocked" : fmtReplay(s.durationMs)) : "—"}</span>
                  </div>
                </div>
                <span style={{ fontSize: "9px", color: s.gpu ? "var(--warn)" : "var(--text-faint)", fontFamily: "var(--font-mono)", cursor: "help", flexShrink: 0 }} title={s.gpu ? "needs a GPU (graphics card) to run" : "runs on a standard processor (CPU)"}>{s.gpu ? "GPU" : "CPU"}</span>
                <span style={{ fontSize: "9px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>${s.costUsd.toFixed(2)}</span>
                {s.structural && u === "pending" ? (
                  <span title={s.preflight} style={chip("var(--danger)", "var(--danger-soft)", "1px solid var(--danger-line)")} data-testid={`dryrun-verdict-${s.order}`}>BLOCKED</span>
                ) : u === "pending" ? (
                  <span style={chip("var(--text-faint)", "var(--line)", "1px solid var(--line)")} data-testid={`dryrun-verdict-${s.order}`}>WAIT</span>
                ) : u === "running" ? (
                  <span style={chip("var(--warn)", "var(--warn-soft)", "1px solid var(--warn-line)")} data-testid={`dryrun-verdict-${s.order}`}>RUN</span>
                ) : s.verdict === "pass" ? (
                  <span style={chip("var(--acc)", "var(--acc-soft)", "1px solid var(--acc-line)")} data-testid={`dryrun-verdict-${s.order}`}>PASS</span>
                ) : (
                  <span style={chip("var(--danger)", "var(--danger-soft)", "1px solid var(--danger-line)")} data-testid={`dryrun-verdict-${s.order}`}>FAIL</span>
                )}
              </div>
              {shown > 0 && (
                <div style={{ marginTop: "6px", paddingTop: "6px", borderTop: "1px solid var(--line-soft)", fontFamily: "var(--font-mono)", fontSize: "9.5px", lineHeight: 1.7 }}>
                  {s.lines.slice(0, shown).map((ln, i) => (
                    <div key={i} style={{ color: i === shown - 1 && u === "running" ? "var(--warn)" : ln.startsWith("✓") ? "var(--acc)" : ln.startsWith("✗") ? "var(--danger)" : "var(--text-mid)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {ln}{u === "running" && i === shown - 1 ? <span className="cursor-blink">_</span> : null}
                    </div>
                  ))}
                </div>
              )}
              {u === "done" && s.verdict === "fail" && s.reason && (
                <div style={{ marginTop: "4px", fontSize: "9.5px", color: s.structural ? "var(--warn)" : "var(--danger)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
                  {s.structural ? "✗ structural — " : ""}{s.preflight ?? s.reason}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Status bar */}
      <div
        data-testid="dryrun-statusbar"
        style={{
          display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap",
          padding: "7px 10px", borderRadius: "4px", marginBottom: "8px",
          background: finished ? (allPassed ? "var(--acc-soft)" : "var(--danger-soft)") : "var(--bg-inset)",
          border: `1px solid ${finished ? (allPassed ? "var(--acc-line)" : "var(--danger-line)") : "var(--line)"}`,
          fontFamily: "var(--font-mono)", fontSize: "10px",
          color: finished ? (allPassed ? "var(--acc)" : "var(--danger)") : "var(--text-dim)",
        }}
      >
        {finished ? (
          <>
            <span data-testid="dryrun-elapsed" style={{ color: "var(--text-faint)" }}>
              {storedView ? "last run · " : ""}completed in {fmtReplay(displaySec * 1000)} · ${costIncurred.toFixed(2)} incurred
            </span>
            <span data-testid="dryrun-summary" style={{ flex: "1 1 100%", lineHeight: 1.5 }}>{summary}</span>
          </>
        ) : (
          <span data-testid="dryrun-elapsed" style={{ flex: 1, minWidth: 0 }}>{liveLine}</span>
        )}
      </div>

      {/* Controls */}
      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
        <button
          data-testid="dryrun-pause"
          onClick={() => setStatus(s => (s === "running" ? "paused" : s === "paused" ? "running" : s))}
          disabled={finished}
          title={status === "paused" ? "resume the replay" : "pause the replay"}
          style={{
            background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "3px 10px",
            color: finished ? "var(--text-faint-2)" : "var(--text-2)", fontSize: "10px", cursor: finished ? "not-allowed" : "pointer",
            fontFamily: "var(--font-mono)", opacity: finished ? 0.5 : 1,
          }}
        >{status === "paused" ? "▶ resume" : "⏸ pause"}</button>
        <button
          data-testid="dryrun-replay"
          onClick={() => { replayedRef.current = true; resetRun(); }}
          title="replay the identical scenario — same seed, same outcome"
          style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "3px 10px", color: "var(--text-2)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
        >↻ replay</button>
        <button
          data-testid="dryrun-scenario"
          onClick={onNewScenario}
          title="reroll the seeded execution risk — structural checks stay identical"
          style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "3px 10px", color: "var(--text-2)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
        >🎲 new scenario</button>
        <span style={{ marginLeft: "auto", fontSize: "9px", color: "var(--text-faint-2)", fontFamily: "var(--font-mono)" }}>
          deterministic — same plan + same seed = same result
        </span>
      </div>
    </div>
  );
}
