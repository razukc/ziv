"use client";

import type { Skill } from "../lib/types";

interface SkillPanelProps {
  open: boolean;
  skills: Skill[];
  loading: boolean;
  onClose: () => void;
  onFetch: () => void;
}

/** Right-hand drawer browsing the NVIDIA skill catalog. */
export default function SkillPanel({ open, skills, loading, onClose, onFetch }: SkillPanelProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        className={`skill-panel-backdrop ${open ? "skill-panel-backdrop-open" : ""}`}
        onClick={onClose}
      />

      {/* Panel */}
      <div className={`skill-panel ${open ? "skill-panel-open" : ""}`}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: "13px", fontWeight: 700, color: "var(--acc)", fontFamily: "var(--font-mono)" }}>nvidia skill catalog</div>
            <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginTop: "2px" }}>{skills.length} skills available</div>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "1px solid var(--line)", borderRadius: "4px", padding: "4px 10px", color: "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--acc)"; e.currentTarget.style.color = "var(--acc)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.color = "var(--text-dim)"; }}
          >
            close
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
          {loading && (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {[1, 2, 3].map(i => (
                <div key={i} className="shimmer-loading" style={{ height: "80px", borderRadius: "4px", border: "1px solid var(--line)" }} />
              ))}
            </div>
          )}
          {!loading && skills.length === 0 && (
            <div style={{ textAlign: "center", padding: "40px 20px" }}>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginBottom: "8px" }}>no skills loaded</div>
              <div style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>switch to live mode and start the backend to fetch the catalog</div>
              <button
                onClick={onFetch}
                style={{ marginTop: "12px", background: "none", border: "1px solid var(--line)", borderRadius: "4px", padding: "6px 14px", color: "var(--acc)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
              >
                retry fetch
              </button>
            </div>
          )}
          {!loading && skills.map((skill) => (
            <div key={skill.id} className="skill-card" style={{ background: "var(--bg-card)", border: "1px solid var(--line)", borderRadius: "6px", padding: "14px", marginBottom: "8px" }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "6px" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>{skill.name}</div>
                  <div style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)", marginTop: "2px" }}>{skill.product}</div>
                </div>
                <div style={{ display: "flex", gap: "6px", flexShrink: 0, marginLeft: "8px" }}>
                  <span style={{
                    fontSize: "10px", padding: "2px 6px", borderRadius: "3px",
                    background: skill.gpu_required ? "var(--warn-soft-2)" : "var(--acc-soft-2)",
                    color: skill.gpu_required ? "var(--warn)" : "var(--acc)",
                    fontFamily: "var(--font-mono)",
                    cursor: "help",
                  }}
                    title={skill.gpu_required ? "needs a GPU (graphics card) to run" : "runs on a standard processor (CPU)"}
                  >
                    {skill.gpu_required ? "GPU" : "CPU"}
                  </span>
                  <span style={{ fontSize: "10px", color: "var(--acc)", fontFamily: "var(--font-mono)" }}>${skill.estimated_cost_usd.toFixed(2)}</span>
                </div>
              </div>
              <div style={{ fontSize: "10px", color: "var(--text-mid)", lineHeight: 1.5, marginBottom: "8px" }}>{skill.description}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                {skill.tags.map((tag) => (
                  <span key={tag} style={{ fontSize: "10px", padding: "1px 6px", borderRadius: "3px", background: "var(--line)", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{tag}</span>
                ))}
              </div>
              <div style={{ marginTop: "8px", fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{skill.id}</div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
