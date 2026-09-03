// Client-side mirror of the backend /api/pipeline/validate checks
// (agent/validation.py), kept in lockstep so mock mode reports the same
// verdicts as a live backend. Used in mock mode (no backend) so the validate
// step works in the demo.

import type { ValidationReport } from "./types";

/** Approximate XML open/close balance, ignoring comments, processing
 * instructions, and self-closing tags. Mirrors the backend heuristic. */
function xmlTagBalanceOk(xml: string): boolean {
  const stripped = xml
    .replace(/<!--[\s\S]*?-->/g, "")   // comments
    .replace(/<\?[\s\S]*?\?>/g, "");   // <?...?>
  const opens = (stripped.match(/<(?![!/?])/g) || []).length;
  const closes = (stripped.match(/<\//g) || []).length;
  const selfClosing = (stripped.match(/\/\s*>/g) || []).length;
  return opens - selfClosing === closes;
}

export function validatePackageFiles(files: Record<string, string>): ValidationReport {
  const report: ValidationReport = { valid: true, errors: [], warnings: [], info: [], score: 100 };
  const fail = (list: ValidationReport["errors"], file: string, message: string, deduction: number) => {
    list.push({ file, message });
    report.score -= deduction;
  };
  const warn = (file: string, message: string, deduction: number) =>
    fail(report.warnings, file, message, deduction);
  const err = (file: string, message: string, deduction: number) =>
    fail(report.errors, file, message, deduction);

  // --- package.xml ---
  const xml = files["package.xml"];
  if (!xml) {
    err("package.xml", "file missing from package", 25);
  } else {
    if (!xml.includes("<?xml")) err("package.xml", "missing XML declaration (<?xml version=...>)", 20);
    if (!xml.includes("<package")) err("package.xml", "missing <package> root element", 20);
    if (!xml.includes("</package>")) err("package.xml", "unclosed <package> element", 15);
    if (!xml.includes("<name>")) warn("package.xml", "missing <name> element", 5);
    if (!xml.includes("<description>")) warn("package.xml", "missing <description> element", 5);
    if (!xml.includes("<maintainer")) warn("package.xml", "missing <maintainer> element", 5);
    if (!xml.includes("<license>")) warn("package.xml", "missing <license> element", 5);
    if (!xml.includes("<buildtool_depend>")) warn("package.xml", "missing <buildtool_depend> (ament_cmake)", 5);
    if (!xml.includes("ament_cmake")) warn("package.xml", "buildtool_depend should be ament_cmake", 3);
    if (!xmlTagBalanceOk(xml)) warn("package.xml", "possible tag mismatch (unbalanced open/close tags)", 5);
    report.info.push({ file: "package.xml", message: "XML structure checked" });
  }

  // --- CMakeLists.txt ---
  const cmake = files["CMakeLists.txt"];
  if (!cmake) {
    err("CMakeLists.txt", "file missing from package", 25);
  } else {
    if (!cmake.includes("cmake_minimum_required")) err("CMakeLists.txt", "missing cmake_minimum_required()", 15);
    if (!cmake.includes("project(")) err("CMakeLists.txt", "missing project() declaration", 15);
    if (!cmake.includes("find_package")) warn("CMakeLists.txt", "no find_package() calls — dependencies may not resolve", 5);
    if (!cmake.includes("ament_package")) warn("CMakeLists.txt", "missing ament_package() — package won't install correctly", 10);
    if (!cmake.includes("ament_cmake")) warn("CMakeLists.txt", "find_package(ament_cmake) not found", 5);
    if ((cmake.match(/\(/g) || []).length !== (cmake.match(/\)/g) || []).length)
      err("CMakeLists.txt", "unbalanced parentheses", 10);
    report.info.push({ file: "CMakeLists.txt", message: "cmake structure checked" });
  }

  // --- launch files ---
  const launches = Object.keys(files).filter(f => f.endsWith(".py") && f.includes("launch"));
  for (const lf of launches) {
    const content = files[lf];
    if (!content.includes("generate_launch_description")) err(lf, "missing generate_launch_description() function", 15);
    if (!content.includes("LaunchDescription")) warn(lf, "LaunchDescription not imported or used", 5);
    if (!content.includes("from launch") && !content.includes("import launch")) warn(lf, "launch module not imported", 5);
    for (const line of content.split("\n")) {
      const spaces = line.length - line.replace(/^\s*/, "").length;
      if (line.trim() && !line.startsWith("#") && spaces % 4 !== 0 && spaces > 0) {
        warn(lf, `non-standard indentation (${spaces} spaces)`, 2);
        break;
      }
    }
    report.info.push({ file: lf, message: "python launch file checked" });
  }
  if (launches.length === 0) warn("launch/", "no launch files found in package", 5);

  // --- pipeline.json ---
  const pj = files["pipeline.json"];
  if (!pj) {
    warn("pipeline.json", "file missing from package", 10);
  } else {
    try {
      const parsed = JSON.parse(pj);
      const subs = parsed?.pipeline?.subtasks;
      if (!parsed?.pipeline) {
        warn("pipeline.json", "missing 'pipeline' key", 5);
      } else if (!Array.isArray(subs)) {
        warn("pipeline.json", "pipeline missing 'subtasks' array", 5);
      } else if (subs.length === 0) {
        warn("pipeline.json", "pipeline has 0 subtasks", 5);
      } else {
        subs.forEach((st: Record<string, unknown>, i: number) => {
          if (!st.skill_id) warn("pipeline.json", `subtask ${i + 1} missing skill_id`, 3);
          if (!st.name) warn("pipeline.json", `subtask ${i + 1} missing name`, 2);
        });
      }
      report.info.push({ file: "pipeline.json", message: "JSON valid, structure checked" });
    } catch {
      err("pipeline.json", "invalid JSON", 20);
    }
  }

  // --- README.md ---
  const readme = files["README.md"];
  if (readme) {
    if (readme.length < 50) warn("README.md", "README is very short (<50 chars)", 3);
    if (!readme.includes("#")) warn("README.md", "README has no markdown headings", 2);
    report.info.push({ file: "README.md", message: "readme checked" });
  }

  // --- package structure ---
  const missing = ["package.xml", "CMakeLists.txt"].filter(f => !files[f]);
  if (missing.length > 0) err("package", `missing required files: ${missing.join(", ")}`, missing.length * 15);

  if (cmake?.includes("add_executable")) {
    report.info.push({ file: "CMakeLists.txt", message: "defines executable targets" });
  } else if (cmake?.includes("ament_package")) {
    report.info.push({ file: "CMakeLists.txt", message: "header-only package (no executables)" });
  }

  report.score = Math.max(0, Math.min(100, report.score));
  report.valid = report.errors.length === 0 && report.score >= 50;
  return report;
}
