"""Structural validation of generated ROS2 packages.

String-level checks over the exported files (package.xml, CMakeLists.txt,
launch python, pipeline.json, README.md) that produce a scored report:
``valid``, ``score`` (0-100), plus errors/warnings/info lists. The checks are
heuristics, not a full parser — good enough to catch broken exports and to
demonstrate the export -> validate loop.
"""

import json
import re


def _xml_tag_balance_ok(xml_content: str) -> bool:
    """Approximate open/close tag balance for package.xml.

    Naive ``<`` / ``>`` counting misreads comments, processing instructions,
    and self-closing tags, so those are stripped/handled first. Well-formed
    XML then balances exactly, so any residual imbalance is a real mismatch.
    """
    stripped = re.sub(r"<!--.*?-->", "", xml_content, flags=re.S)   # comments
    stripped = re.sub(r"<\?.*?\?>", "", stripped, flags=re.S)       # <?...?>
    opens = len(re.findall(r"<(?![!/?])", stripped))                # <tag
    closes = len(re.findall(r"</", stripped))                        # </tag
    self_closing = len(re.findall(r"/\s*>", stripped))              # <.../>
    return (opens - self_closing) == closes


def validate_package(files: dict, package_name: str = "") -> dict:
    """Validate a generated ROS2 package for common issues.

    Returns a structured report with errors, warnings, info, a 0-100 score,
    and an overall ``valid`` flag.
    """
    report = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "info": [],
        "score": 100,
    }

    def add(level: str, file: str, message: str, deduction: int) -> None:
        report[level].append({"file": file, "message": message})
        report["score"] -= deduction

    # --- Validate package.xml ---
    if "package.xml" in files:
        xml_content = files["package.xml"]
        # Check XML structure
        if "<?xml" not in xml_content:
            add("errors", "package.xml", "missing XML declaration (<?xml version=...>)", 20)
        if "<package" not in xml_content:
            add("errors", "package.xml", "missing <package> root element", 20)
        if "</package>" not in xml_content:
            add("errors", "package.xml", "unclosed <package> element", 15)
        if "<name>" not in xml_content:
            add("warnings", "package.xml", "missing <name> element", 5)
        if "<description>" not in xml_content:
            add("warnings", "package.xml", "missing <description> element", 5)
        if "<maintainer" not in xml_content:
            add("warnings", "package.xml", "missing <maintainer> element", 5)
        if "<license>" not in xml_content:
            add("warnings", "package.xml", "missing <license> element", 5)
        if "<buildtool_depend>" not in xml_content:
            add("warnings", "package.xml", "missing <buildtool_depend> (ament_cmake)", 5)
        if "ament_cmake" not in xml_content:
            add("warnings", "package.xml", "buildtool_depend should be ament_cmake", 3)
        if not _xml_tag_balance_ok(xml_content):
            add("warnings", "package.xml",
                "possible tag mismatch (unbalanced open/close tags)", 5)
        report["info"].append({"file": "package.xml", "message": "XML structure checked"})
    else:
        add("errors", "package.xml", "file missing from package", 25)

    # --- Validate CMakeLists.txt ---
    if "CMakeLists.txt" in files:
        cmake_content = files["CMakeLists.txt"]
        if "cmake_minimum_required" not in cmake_content:
            add("errors", "CMakeLists.txt", "missing cmake_minimum_required()", 15)
        if "project(" not in cmake_content:
            add("errors", "CMakeLists.txt", "missing project() declaration", 15)
        if "find_package" not in cmake_content:
            add("warnings", "CMakeLists.txt",
                "no find_package() calls — dependencies may not resolve", 5)
        if "ament_package" not in cmake_content:
            add("warnings", "CMakeLists.txt",
                "missing ament_package() — package won't install correctly", 10)
        if "ament_cmake" not in cmake_content:
            add("warnings", "CMakeLists.txt",
                "find_package(ament_cmake) not found", 5)
        # Check parentheses balance
        opens = cmake_content.count("(")
        closes = cmake_content.count(")")
        if opens != closes:
            add("errors", "CMakeLists.txt",
                f"unbalanced parentheses: {opens} opens vs {closes} closes", 10)
        report["info"].append({"file": "CMakeLists.txt", "message": "cmake structure checked"})
    else:
        add("errors", "CMakeLists.txt", "file missing from package", 25)

    # --- Validate launch file ---
    launch_files = [k for k in files if k.endswith(".py") and "launch" in k]
    for launch_file in launch_files:
        py_content = files[launch_file]
        if "def generate_launch_description" not in py_content:
            add("errors", launch_file,
                "missing generate_launch_description() function", 15)
        if "LaunchDescription" not in py_content:
            add("warnings", launch_file,
                "LaunchDescription not imported or used", 5)
        if "from launch" not in py_content and "import launch" not in py_content:
            add("warnings", launch_file, "launch module not imported", 5)
        # Check indentation (basic Python check)
        lines = py_content.split("\n")
        for i, line in enumerate(lines, 1):
            if line.strip() and not line.startswith("#"):
                spaces = len(line) - len(line.lstrip())
                if spaces % 4 != 0 and spaces > 0:
                    add("warnings", launch_file,
                        f"line {i}: non-standard indentation ({spaces} spaces)", 2)
                    break  # Only report first
        report["info"].append({"file": launch_file, "message": "python launch file checked"})
    if not launch_files:
        add("warnings", "launch/", "no launch files found in package", 5)

    # --- Validate pipeline.json ---
    if "pipeline.json" in files:
        json_content = files["pipeline.json"]
        try:
            parsed = json.loads(json_content)
            if "pipeline" not in parsed:
                add("warnings", "pipeline.json", "missing 'pipeline' key", 5)
            elif "subtasks" not in parsed["pipeline"]:
                add("warnings", "pipeline.json",
                    "pipeline missing 'subtasks' array", 5)
            else:
                subtasks = parsed["pipeline"]["subtasks"]
                if len(subtasks) == 0:
                    add("warnings", "pipeline.json", "pipeline has 0 subtasks", 5)
                else:
                    for i, st in enumerate(subtasks):
                        if "skill_id" not in st:
                            add("warnings", "pipeline.json",
                                f"subtask {i + 1} missing skill_id", 3)
                        if "name" not in st:
                            add("warnings", "pipeline.json",
                                f"subtask {i + 1} missing name", 2)
            report["info"].append({"file": "pipeline.json",
                                   "message": "JSON valid, structure checked"})
        except json.JSONDecodeError as e:
            add("errors", "pipeline.json", f"invalid JSON: {e}", 20)
    else:
        add("warnings", "pipeline.json", "file missing from package", 10)

    # --- Validate README ---
    if "README.md" in files:
        readme = files["README.md"]
        if len(readme) < 50:
            add("warnings", "README.md", "README is very short (<50 chars)", 3)
        if "#" not in readme:
            add("warnings", "README.md", "README has no markdown headings", 2)
        report["info"].append({"file": "README.md", "message": "readme checked"})

    # --- Package structure check ---
    required_files = ["package.xml", "CMakeLists.txt"]
    missing = [f for f in required_files if f not in files]
    if missing:
        add("errors", "package",
            f"missing required files: {', '.join(missing)}", len(missing) * 15)

    # Check for executables in CMakeLists
    if "CMakeLists.txt" in files:
        cmake = files["CMakeLists.txt"]
        if "add_executable" in cmake:
            report["info"].append({"file": "CMakeLists.txt",
                                   "message": "defines executable targets"})
        elif "ament_package" in cmake:
            report["info"].append({"file": "CMakeLists.txt",
                                   "message": "header-only package (no executables)"})

    # Clamp score
    report["score"] = max(0, min(100, report["score"]))

    # Determine overall validity
    report["valid"] = len(report["errors"]) == 0 and report["score"] >= 50

    return report
