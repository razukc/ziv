"use client";

import { ROBOT_OPTIONS } from "../lib/mock-data";
import type { HistoryItem } from "../lib/types";
import { CompareRow } from "./ui";

interface PipelineHistoryProps {
  history: HistoryItem[];
  compareIds: string[];
  expandedHistory: Set<string>;
  onToggleCompare: (id: string) => void;
  onClearCompare: () => void;
  onToggleExpand: (id: string) => void;
  onOpen: (item: HistoryItem) => void;
}

/** Persistent pipeline history with expandable cards, side-by-side compare,
 *  and reopen-in-editor so past composes can be tweaked and re-exported. */
export default function PipelineHistory({
  history, compareIds, expandedHistory, onToggleCompare, onClearCompare, onToggleExpand, onOpen,
}: PipelineHistoryProps) {
  return (
    <div style={{ marginTop: "40px" }} className="fade-in-up">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
        <div>
          <div style={{ fontSize: "11px", color: "var(--acc)", fontFamily: "var(--font-mono)", fontWeight: 700 }}>pipeline history</div>
          <div style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", marginTop: "2px" }}>{history.length} pipeline{history.length !== 1 ? "s" : ""} composed</div>
        </div>
        {compareIds.length >= 2 && (
          <button
            onClick={onClearCompare}
            style={{ background: "var(--acc-soft-2)", border: "1px solid var(--acc-line-hi)", borderRadius: "4px", padding: "4px 10px", color: "var(--acc)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
          >
            compare ({compareIds.length})
          </button>
        )}
      </div>

      {/* History cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "8px", marginBottom: "16px" }}>
        {[...history].reverse().map((item) => {
          const isSelected = compareIds.includes(item.id);
          const isExpanded = expandedHistory.has(item.id);
          const robotOpt = ROBOT_OPTIONS.find(r => r.value === item.robot);
          return (
            <div
              key={item.id}
              className={`history-card ${isSelected ? "history-card-selected" : ""}`}
              style={{
                background: "var(--bg-card)",
                border: isSelected ? "1px solid var(--acc)" : "1px solid var(--line)",
                borderRadius: "6px",
                padding: "12px",
                position: "relative",
              }}
            >
              {/* Compare checkbox */}
              <div style={{ position: "absolute", top: "8px", right: "8px" }}>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleCompare(item.id);
                  }}
                  style={{
                    width: "16px", height: "16px", borderRadius: "3px",
                    border: isSelected ? "1px solid var(--acc)" : "1px solid var(--text-faint)",
                    background: isSelected ? "var(--acc-fill)" : "none",
                    cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: "8px", color: "var(--inverse)",
                  }}
                >
                  {isSelected && "✓"}
                </button>
              </div>

              {/* Card content */}
              <div onClick={() => onToggleExpand(item.id)} style={{ cursor: "pointer" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
                  <span style={{ fontSize: "14px" }}>{robotOpt?.icon}</span>
                  <span style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>{robotOpt?.label}</span>
                  <span style={{ fontSize: "10px", color: "var(--text-faint)", background: "var(--line)", padding: "1px 5px", borderRadius: "3px", fontFamily: "var(--font-mono)" }}>{item.result.pipeline.task_type}</span>
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-1)", marginBottom: "6px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}>
                  "{item.task}"
                </div>
                <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                  <span>{item.result.pipeline.subtasks.length} steps</span>
                  <span style={{ color: "var(--acc)" }}>${item.result.pipeline.total_estimated_cost_usd.toFixed(2)}</span>
                  <span style={{ color: item.result.pipeline.risk_assessment === "low" ? "var(--acc)" : "var(--warn)" }}>{item.result.pipeline.risk_assessment}</span>
                  {item.dryrun && (
                    <span
                      data-testid="history-dryrun"
                      title={`dry-run ${item.dryrun.verdicts.every(v => v === "pass") ? "passed" : "halted"} · ${item.dryrun.verdicts.filter(v => v === "pass").length}/${item.dryrun.verdicts.length} steps · seed 0x${item.dryrun.seed.toString(16).padStart(4, "0")} — open in editor and run sim dry-run to see details`}
                      style={{ color: item.dryrun.verdicts.every(v => v === "pass") ? "var(--acc)" : "var(--danger)" }}
                    >
                      {item.dryrun.verdicts.every(v => v === "pass") ? "🧪 pass" : "🧪 fail"} · {item.dryrun.elapsedSec}s · 0x{item.dryrun.seed.toString(16).padStart(4, "0")}
                    </span>
                  )}
                  {item.composeStats && (
                    <span
                      data-testid="history-compose-time"
                      title={`compose took ${Math.max(1, Math.round(item.composeStats.seconds))}s${item.composeStats.retries > 0 ? ` — auto-retried ${item.composeStats.retries}×, healed on its own` : ""}`}
                      style={{ color: item.composeStats.retries > 0 ? "var(--warn)" : "var(--text-faint)" }}
                    >
                      ⏱ {Math.max(1, Math.round(item.composeStats.seconds))}s
                      {item.composeStats.retries > 0 && ` · retried ${item.composeStats.retries}×`}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", marginTop: "4px" }}>
                  {new Date(item.timestamp).toLocaleTimeString()}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "6px" }}>
                  <button
                    title="open in editor — restore this pipeline and tweak steps"
                    onClick={(e) => { e.stopPropagation(); onOpen(item); }}
                    style={{
                      background: "var(--acc-soft-2)", border: "1px solid var(--acc-line-hi)",
                      borderRadius: "3px", padding: "2px 8px", color: "var(--acc)",
                      fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)", fontWeight: 600,
                    }}
                  >
                    ↪ open in editor
                  </button>
                  {item.kind === "live" && item.pipelineId ? (
                    <span title="composed live — stored in the shared store" style={{ fontSize: "9px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>
                      live · {item.pipelineId.slice(0, 9)}
                    </span>
                  ) : (
                    <span title="demo pipeline — stored in this browser only" style={{ fontSize: "9px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>
                      mock · local
                    </span>
                  )}
                </div>
              </div>

              {/* Expanded pipeline details */}
              {isExpanded && (
                <div style={{ marginTop: "10px", borderTop: "1px solid var(--line)", paddingTop: "10px" }}>
                  {item.result.pipeline.subtasks.map((st, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: "6px", padding: "3px 0", fontSize: "10px", fontFamily: "var(--font-mono)" }}>
                      <span style={{ color: "var(--text-faint)", width: "12px" }}>{st.order}</span>
                      <span style={{ color: "var(--text-2)", flex: 1 }}>{st.name}</span>
                      <span style={{ color: "var(--acc)" }}>${st.estimated_cost_usd.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Side-by-side comparison */}
      {compareIds.length >= 2 && (
        <div style={{ background: "var(--bg-raised)", border: "1px solid var(--line)", borderRadius: "6px", padding: "16px", marginBottom: "20px" }} className="fade-in-up">
          <div style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)", marginBottom: "12px", letterSpacing: "0.5px" }}>side_by_side_comparison</div>
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${compareIds.length}, 1fr)`, gap: "12px" }}>
            {compareIds.map(id => {
              const item = history.find(h => h.id === id);
              if (!item) return null;
              const robotOpt = ROBOT_OPTIONS.find(r => r.value === item.robot);
              return (
                <div key={id} style={{ background: "var(--bg-card)", border: "1px solid var(--line)", borderRadius: "4px", padding: "12px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
                    <span style={{ fontSize: "14px" }}>{robotOpt?.icon}</span>
                    <span style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>{robotOpt?.label}</span>
                  </div>
                  <div style={{ fontSize: "10px", color: "var(--text-2)", marginBottom: "8px", fontFamily: "var(--font-mono)" }}>
                    "{item.task.length > 40 ? item.task.slice(0, 40) + "..." : item.task}"
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <CompareRow label="steps" value={String(item.result.pipeline.subtasks.length)} />
                    <CompareRow label="cost" value={`$${item.result.pipeline.total_estimated_cost_usd.toFixed(2)}`} color="var(--acc)" />
                    <CompareRow label="risk" value={item.result.pipeline.risk_assessment} color={item.result.pipeline.risk_assessment === "low" ? "var(--acc)" : "var(--warn)"} />
                    <CompareRow label="time" value={`${item.result.pipeline.estimated_time_minutes}min`} />
                    <CompareRow label="type" value={item.result.pipeline.task_type} />
                  </div>
                  <div style={{ marginTop: "8px", borderTop: "1px solid var(--line)", paddingTop: "8px" }}>
                    {item.result.pipeline.subtasks.map((st, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: "4px", padding: "2px 0", fontSize: "10px", fontFamily: "var(--font-mono)" }}>
                        <span title={st.gpu_required ? "needs a GPU (graphics card) to run" : "runs on a standard processor (CPU)"} style={{ color: st.gpu_required ? "var(--warn)" : "var(--text-faint)" }}>{st.gpu_required ? "⚡" : "🖥"}</span>
                        <span style={{ color: "var(--text-mid)", flex: 1 }}>{st.name}</span>
                        <span style={{ color: "var(--acc)" }}>${st.estimated_cost_usd.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
