"use client";

import React from "react";

// --- Stat Block (used in results summary) ---

export function StatBlock({ label, value, color, hint }: { label: string; value: string; color?: string; hint?: string }) {
  return (
    <div title={hint} style={{ background: "var(--bg-raised)", border: "1px solid var(--line)", borderRadius: "4px", padding: "12px 14px", textAlign: "center" }}>
      <div style={{ fontSize: "16px", fontWeight: 800, color: color || "var(--text-hi)", fontFamily: "var(--font-mono)" }}>{value}</div>
      <div style={{ fontSize: "11px", color: "var(--text-faint)", marginTop: "2px", fontFamily: "var(--font-mono)", letterSpacing: "0.5px" }}>{label}</div>
    </div>
  );
}

// --- Meta Item (used in pipeline metadata grid) ---

export function MetaItem({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 8px", background: "var(--bg-inset)", borderRadius: "3px" }}>
      <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{label}</span>
      <span style={{ fontSize: "10px", color: "var(--text-2)", fontFamily: "var(--font-mono)" }}>{value}</span>
    </div>
  );
}

// --- Export Option (clickable row with copy-on-click) ---

export function ExportOption({ icon, label, desc, command }: { icon: string; label: string; desc: string; command: string }) {
  const [copied, setCopied] = React.useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div
      onClick={handleCopy}
      style={{ display: "flex", alignItems: "center", gap: "10px", padding: "10px 12px", background: "var(--bg-inset)", borderRadius: "4px", border: copied ? "1px solid var(--acc-line-hi)" : "1px solid var(--line)", cursor: "pointer", transition: "all 0.15s ease" }}
    >
      <span style={{ fontSize: "16px", flexShrink: 0 }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "11px", fontWeight: 600, color: copied ? "var(--acc)" : "var(--text-1)", fontFamily: "var(--font-mono)" }}>{label}</div>
        <div style={{ fontSize: "9px", color: "var(--text-faint-2)", marginTop: "2px" }}>{desc}</div>
        <div style={{ fontSize: "9px", color: "var(--acc)", fontFamily: "var(--font-mono)", marginTop: "4px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{command}</div>
      </div>
      <span style={{ fontSize: "10px", color: copied ? "var(--acc)" : "var(--text-faint)", fontFamily: "var(--font-mono)", flexShrink: 0, transition: "color 0.15s" }}>{copied ? "copied!" : "click to copy"}</span>
    </div>
  );
}

// --- Exported File (expandable file card with copy) ---

export function ExportedFile({ filename, content }: { filename: string; content: string }) {
  const [copied, setCopied] = React.useState(false);
  const [expanded, setExpanded] = React.useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  const ext = filename.split(".").pop() || "";
  const icon = ext === "xml" ? "\u{1F4CB}" : ext === "txt" ? "\u2699\uFE0F" : ext === "json" ? "{ }" : ext === "py" ? "\u{1F40D}" : "\u{1F4C4}";
  return (
    <div style={{ background: "var(--bg-card)", border: "1px solid var(--line)", borderRadius: "4px", overflow: "hidden" }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{ display: "flex", alignItems: "center", gap: "8px", padding: "8px 10px", cursor: "pointer" }}
      >
        <span style={{ fontSize: "10px" }}>{icon}</span>
        <span style={{ fontSize: "10px", color: "var(--text-1)", fontFamily: "var(--font-mono)", flex: 1 }}>{filename}</span>
        <span style={{ fontSize: "10px", color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{content.length} chars</span>
        <button
          onClick={(e) => { e.stopPropagation(); handleCopy(); }}
          style={{ background: "none", border: "1px solid var(--line)", borderRadius: "3px", padding: "2px 8px", color: copied ? "var(--acc)" : "var(--text-dim)", fontSize: "10px", cursor: "pointer", fontFamily: "var(--font-mono)" }}
        >
          {copied ? "copied" : "copy"}
        </button>
        <span style={{ fontSize: "8px", color: "var(--text-faint)", transform: expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}>{"\u25BC"}</span>
      </div>
      {expanded && (
        <div style={{ borderTop: "1px solid var(--line)", padding: "10px", background: "var(--bg-inset)", maxHeight: "300px", overflow: "auto" }}>
          <pre style={{ margin: 0, fontSize: "9px", color: "var(--text-2)", fontFamily: "var(--font-mono)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{content}</pre>
        </div>
      )}
    </div>
  );
}

// --- Compare Row (used in side-by-side comparison) ---

export function CompareRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 0" }}>
      <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{label}</span>
      <span style={{ fontSize: "10px", color: color || "var(--text-2)", fontFamily: "var(--font-mono)" }}>{value}</span>
    </div>
  );
}
