"use client";

import type { CSSProperties } from "react";
import type { Pipeline } from "../lib/types";
import { plainStep } from "../lib/plain";

const editBtnStyle: CSSProperties = {
  background: "none", border: "1px solid var(--text-faint)", borderRadius: "3px",
  color: "var(--acc)", fontSize: "10px", cursor: "pointer",
  padding: "2px 7px", fontFamily: "var(--font-mono)", lineHeight: "1.3",
};
const removeBtnStyle: CSSProperties = {
  ...editBtnStyle, color: "var(--danger)", borderColor: "var(--danger-line)",
};

interface PipelineTimelineProps {
  pipeline: Pipeline;
  editMode: boolean;
  onBeginEdit: () => void;
  onBeginVariation: () => void;
  onDoneEdit: () => void;
  onCancelEdit: () => void;
  onMoveStep: (index: number, dir: -1 | 1) => void;
  onRemoveStep: (index: number) => void;
}

/** Ordered pipeline steps with the human edit controls (reorder/remove) and
 *  the create-variation entry point. */
export default function PipelineTimeline({
  pipeline, editMode, onBeginEdit, onBeginVariation, onDoneEdit, onCancelEdit, onMoveStep, onRemoveStep,
}: PipelineTimelineProps) {
  const stepCount = pipeline.subtasks.length;
  return (
    <div className="fade-in-up" style={{ marginBottom: "20px", animationDelay: "0.1s" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
        <h3 style={{ fontSize: "11px", color: "var(--acc)", margin: 0, fontFamily: "var(--font-mono)" }}>pipeline</h3>
        <span style={{ fontSize: "10px", color: "var(--text-faint)", background: "var(--line)", padding: "2px 6px", borderRadius: "3px", fontFamily: "var(--font-mono)" }}>{pipeline.task_type}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: "6px" }}>
          {!editMode ? (
            <>
              <button
                onClick={onBeginVariation}
                title="compose a new pipeline adapted from this one"
                style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "3px 10px", color: "var(--text-2)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)", transition: "all 0.15s ease" }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--acc)"; e.currentTarget.style.color = "var(--acc)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.color = "var(--text-2)"; }}
              >
                🧬 create variation
              </button>
              <button
                onClick={onBeginEdit}
                style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "3px 10px", color: "var(--text-2)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)", transition: "all 0.15s ease" }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--acc)"; e.currentTarget.style.color = "var(--acc)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.color = "var(--text-2)"; }}
              >
                ✏️ edit steps
              </button>
            </>
          ) : (
            <>
              <button onClick={onDoneEdit} style={{ ...editBtnStyle, background: "var(--acc-soft-2)", borderColor: "var(--acc-line-hi)" }}>done</button>
              <button onClick={onCancelEdit} style={editBtnStyle}>cancel</button>
            </>
          )}
        </div>
      </div>
      {editMode && (
        <div style={{ marginBottom: "10px", padding: "8px 12px", background: "var(--acc-soft)", border: "1px solid var(--acc-line)", borderRadius: "4px", fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>
          edit mode — reorder (↑/↓), remove (✕), then re-export without an LLM call
        </div>
      )}
      <div style={{ position: "relative", paddingLeft: "20px" }}>
        <div style={{ position: "absolute", left: "7px", top: "8px", bottom: "8px", width: "1px", background: "var(--line)" }} />
        {pipeline.subtasks.map((st, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "10px 12px", borderRadius: "4px", marginBottom: "2px", position: "relative", ...(editMode ? { border: "1px solid var(--acc-line)", background: "var(--bg-raised)" } : {}) }}>
            <div style={{ position: "absolute", left: "-20px", width: "12px", height: "12px", borderRadius: "50%", background: editMode ? "var(--warn)" : "var(--acc-fill)", border: "2px solid var(--bg)" }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>
                <span style={{ color: "var(--text-faint-2)", marginRight: "6px", fontFamily: "var(--font-mono)" }}>{st.order}.</span>{st.name}
              </div>
              <div style={{ fontSize: "10px", color: "var(--text-faint-2)", marginTop: "2px" }}>{st.description}</div>
            </div>
            <div style={{ display: "flex", gap: "6px", alignItems: "center", flexShrink: 0 }}>
              {editMode && (
                <div style={{ display: "flex", gap: "4px", marginRight: "2px" }}>
                  <button
                    onClick={() => onMoveStep(i, -1)}
                    disabled={i === 0}
                    title="move up"
                    style={{ ...editBtnStyle, ...(i === 0 ? { opacity: 0.3, cursor: "not-allowed" } : {}) }}
                  >↑</button>
                  <button
                    onClick={() => onMoveStep(i, 1)}
                    disabled={i === stepCount - 1}
                    title="move down"
                    style={{ ...editBtnStyle, ...(i === stepCount - 1 ? { opacity: 0.3, cursor: "not-allowed" } : {}) }}
                  >↓</button>
                  <button onClick={() => onRemoveStep(i)} title="remove step" style={removeBtnStyle}>✕</button>
                </div>
              )}
              <span title={plainStep(st)} style={{ fontSize: "10px", color: "var(--acc)", background: "var(--acc-soft-2)", padding: "2px 6px", borderRadius: "3px", fontFamily: "var(--font-mono)", cursor: "help" }}>{st.skill_id}</span>
              <span title={st.gpu_required ? "needs a GPU (graphics card) to run" : "runs on a standard processor (CPU)"} style={{ fontSize: "10px", color: st.gpu_required ? "var(--warn)" : "var(--text-faint)", padding: "2px 5px", borderRadius: "3px", fontFamily: "var(--font-mono)", cursor: "help" }}>{st.gpu_required ? "GPU" : "CPU"}</span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)", minWidth: "36px", textAlign: "right", fontFamily: "var(--font-mono)" }}>{`$${st.estimated_cost_usd.toFixed(2)}`}</span>
            </div>
          </div>
        ))}
      </div>
      {editMode && (
        <div style={{ marginTop: "10px", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: "var(--bg-card)", borderRadius: "4px", border: "1px solid var(--line)", fontFamily: "var(--font-mono)", fontSize: "10px" }}>
          <span style={{ color: "var(--text-dim)" }}>{stepCount} steps · ${pipeline.total_estimated_cost_usd.toFixed(2)} total</span>
          <span style={{ color: "var(--acc)" }}>re-export applies changes — no LLM call</span>
        </div>
      )}
    </div>
  );
}
