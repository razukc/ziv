"use client";

import type { Pipeline } from "../lib/types";
import { plainStep } from "../lib/plain";

/**
 * "In plain words" card shown above the technical timeline: restates what the
 * composed plan actually does, one everyday sentence per step, so the results
 * make sense without a robotics background. Mirrors edits automatically since
 * it derives from the displayed pipeline.
 */
export default function PlainSummary({ pipeline }: { pipeline: Pipeline }) {
  const stepCount = pipeline.subtasks.length;
  return (
    <div
      data-testid="plain-summary"
      className="fade-in-up"
      style={{
        marginBottom: "20px",
        background: "var(--bg-inset)",
        border: "1px solid var(--line)",
        borderRadius: "6px",
        padding: "14px 16px",
      }}
    >
      <div
        style={{
          fontSize: "11px",
          color: "var(--acc)",
          fontFamily: "var(--font-mono)",
          marginBottom: "8px",
          letterSpacing: "0.5px",
        }}
      >
        in plain words — what this plan does
      </div>
      <div style={{ fontSize: "12px", color: "var(--text-2)", lineHeight: 1.75 }}>
        <div style={{ marginBottom: "6px" }}>
          “{pipeline.task}” breaks down into {stepCount} step{stepCount === 1 ? "" : "s"}:
        </div>
        {pipeline.subtasks.map((st, i) => (
          <div key={i} style={{ display: "flex", gap: "10px", padding: "1px 0" }}>
            <span
              style={{
                color: "var(--acc)",
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                flexShrink: 0,
                width: "18px",
                textAlign: "right",
              }}
            >
              {i + 1}.
            </span>
            <span style={{ flex: 1 }}>{plainStep(st)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
