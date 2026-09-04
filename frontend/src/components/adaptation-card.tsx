import type { AdaptationReport } from "../lib/types";
import { adaptationCounts, robotLabel } from "../lib/adaptation";

interface AdaptationCardProps {
  report: AdaptationReport;
}

const BADGE_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  "still-applies": { bg: "var(--acc-soft-2)", fg: "var(--acc)", label: "still applies" },
  reworded: { bg: "var(--acc-soft-2)", fg: "var(--acc)", label: "kept + reworded" },
  new: { bg: "var(--warn-soft-2)", fg: "var(--warn)", label: "new" },
};

/**
 * "Why did this plan change?" — the seeded-variation diff, per step: what was
 * carried over (and why it still applies), what was added for the new
 * task/robot, and what was dropped (robot anatomy or task rewrite). Derived
 * deterministically from the seed and the result — no extra LLM call.
 */
export default function AdaptationCard({ report }: AdaptationCardProps) {
  const counts = adaptationCounts(report);
  return (
    <div
      data-testid="adaptation-card"
      className="fade-in-up"
      style={{ marginBottom: "20px", background: "var(--bg-card)", border: "1px solid var(--acc-line)", borderRadius: "6px", padding: "14px 16px" }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "10px", flexWrap: "wrap", marginBottom: "10px" }}>
        <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--acc)", fontFamily: "var(--font-mono)" }}>
          🧬 adaptation — how this plan changed
        </span>
        <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
          {robotLabel(report.fromRobot)} → {robotLabel(report.toRobot)} · {counts.kept} carried · {counts.added} added · {counts.dropped} dropped
        </span>
      </div>

      {report.steps.map(step => {
        const badge = BADGE_STYLE[step.badge];
        return (
          <div key={`s${step.order}`} style={{ display: "flex", alignItems: "flex-start", gap: "8px", padding: "3px 0" }}>
            <span style={{ flexShrink: 0, fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", width: "18px", textAlign: "right" }}>{step.order}.</span>
            <span style={{ flexShrink: 0, fontSize: "9px", padding: "1px 6px", borderRadius: "3px", background: badge.bg, color: badge.fg, fontFamily: "var(--font-mono)", marginTop: "1px" }}>
              {badge.label}
            </span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <span style={{ fontSize: "11px", color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>{step.name}</span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)", marginLeft: "8px" }}>{step.note}</span>
            </div>
          </div>
        );
      })}

      {report.dropped.map(d => (
        <div key={`d${d.order}`} style={{ display: "flex", alignItems: "flex-start", gap: "8px", padding: "3px 0" }}>
          <span style={{ flexShrink: 0, fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", width: "18px", textAlign: "right" }}>{d.order}.</span>
          <span style={{ flexShrink: 0, fontSize: "9px", padding: "1px 6px", borderRadius: "3px", background: "var(--warn-soft)", color: "var(--warn)", fontFamily: "var(--font-mono)", marginTop: "1px" }}>
            dropped
          </span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <span style={{ fontSize: "11px", color: "var(--text-1)", fontFamily: "var(--font-mono)", textDecoration: "line-through", textDecorationColor: "var(--warn-line)" }}>{d.name}</span>
            <span style={{ fontSize: "10px", color: "var(--warn)", marginLeft: "8px" }}>{d.reason}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
