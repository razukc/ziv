"""ROS2 package generation for a composed pipeline.

Turns an ordered pipeline (task, robot, subtasks with skill ids) into a
complete, buildable ament_cmake package: package.xml, CMakeLists.txt,
launch/pipeline.launch.py, pipeline.json, and README.md. Pure string
generation over the pipeline + skill catalog — no LLM involved.
"""

import hashlib
import json
from datetime import datetime, timezone

from skill_registry import SKILL_CATALOG


def build_ros2_package(pipeline: dict, robot: str, pipeline_id: str) -> dict:
    """Generate a full ROS2 package dict for ``pipeline``.

    Returns the export payload: package name, content hash, files, and
    metadata. ``pipeline_id`` is embedded so downstream artifacts reference
    the same stored pipeline.
    """
    # Generate package name from robot + task type
    robot_slug = robot.replace("unitree-", "").replace("1x-", "neo-")
    task_type = pipeline.get("task_type", "pipeline")
    pkg_name = f"sf_{robot_slug}_{task_type}"

    # Generate pipeline hash for versioning
    pipeline_json = json.dumps(pipeline, sort_keys=True)
    pipeline_hash = hashlib.sha256(pipeline_json.encode()).hexdigest()[:8]

    # Build skill dependencies
    skill_deps = []
    for subtask in pipeline.get("subtasks", []):
        skill = SKILL_CATALOG.get(subtask.get("skill_id", ""), {})
        product = skill.get("product", "")
        if "ROS2" in product or "ROS" in product:
            skill_deps.append("rclcpp")
        if "Isaac Sim" in product:
            skill_deps.append("isaac_ros_common")
        if "Omniverse" in product:
            skill_deps.append("omniverse_kit")

    # Deduplicate
    skill_deps = list(set(skill_deps))

    # Generate package.xml
    pkg_xml = f"""<?xml version="1.0"?>
<?xml-model href="http://download.ros.org/schema/package_format3.xsd" schematypens="http://www.w3.org/2001/XMLSchema"?>
<package format="3">
  <name>{pkg_name}</name>
  <version>1.0.0</version>
  <description>Auto-generated SkillForge pipeline for {robot}</description>

  <!-- SkillForge Pipeline Metadata -->
  <maintainer email="noreply@skillforge.dev">SkillForge</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_cmake</buildtool_depend>

  <!-- Pipeline Dependencies -->
  <depend>rclcpp</depend>
  <depend>std_msgs</depend>
  <depend>geometry_msgs</depend>
  <depend>sensor_msgs</depend>
  {chr(10).join(f'  <depend>{dep}</depend>' for dep in skill_deps if dep not in ['rclcpp'])}

  <!-- NVIDIA Skill Dependencies -->
  <exec_depend>isaac_ros_common</exec_depend>
  <exec_depend>isaac_ros_nvenc</exec_depend>

  <export>
    <build_type>ament_cmake</build_type>
  </export>
</package>
"""

    # Generate CMakeLists.txt
    subtask_names = [s.get("name", f"step_{i}")
                     for i, s in enumerate(pipeline.get("subtasks", []), 1)]
    cmakeLists = f"""cmake_minimum_required(VERSION 3.8)
project({pkg_name})

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

# Pipeline nodes: {', '.join(subtask_names)}
set(PIPELINE_NODES
  {' '.join(subtask_names)}
)

foreach(NODE ${{PIPELINE_NODES}})
  add_executable(${{NODE}}_node src/${{NODE}}.cpp)
  target_include_directories(${{NODE}}_node PUBLIC
    $<BuildInterface:${{CMAKE_CURRENT_SOURCE_DIR}}/include>
    $<InstallInterface:include>)
  target_compile_features(${{NODE}}_node PUBLIC cxx_std_17)
  ament_target_dependencies(${{NODE}}_node
    rclcpp
    std_msgs
    geometry_msgs
    sensor_msgs
  )
  install(TARGETS ${{NODE}}_node
    DESTINATION lib/${{PROJECT_NAME}})
endforeach()

install(DIRECTORY
  launch
  config
  DESTINATION share/${{PROJECT_NAME}})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
"""

    # Generate launch file
    launch_nodes = []
    for i, subtask in enumerate(pipeline.get("subtasks", []), 1):
        name = subtask.get("name", f"step_{i}")
        skill_id = subtask.get('skill_id', '')
        node_str = (
            f'        Node(\n'
            f'            package="{pkg_name}",\n'
            f'            executable="{name}_node",\n'
            f'            name="{name}",\n'
            f'            output="screen",\n'
            f'            parameters=[{{"step": {i}, "skill_id": "{skill_id}"}}]\n'
            f'        )'
        )
        launch_nodes.append(node_str)

    launch_py = f"""from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
{chr(10).join(launch_nodes)}
    ])
"""

    # Generate pipeline.json (the actual pipeline data)
    pipeline_export = {
        "pipeline": pipeline,
        "metadata": {
            "generated_by": "SkillForge v0.1.0",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "pipeline_hash": pipeline_hash,
            "pipeline_id": pipeline_id,
            "robot": robot,
            "total_cost_usd": pipeline.get("total_estimated_cost_usd", 0),
            "estimated_time_minutes": pipeline.get("estimated_time_minutes", 0),
            "risk_assessment": pipeline.get("risk_assessment", "unknown"),
        },
        "export_format": "ros2_humble",
        "package_name": pkg_name,
    }

    # Generate README
    readme = f"""# {pkg_name}

Auto-generated by **SkillForge** — Natural language to robot skill pipelines.

## Pipeline Overview

- **Task:** {pipeline.get('task', robot)}
- **Robot:** {robot}
- **Type:** {task_type}
- **Total Cost:** ${pipeline.get('total_estimated_cost_usd', 0):.2f}
- **Estimated Time:** {pipeline.get('estimated_time_minutes', 0)} minutes
- **Risk:** {pipeline.get('risk_assessment', 'unknown').upper()}

## Pipeline Steps

| # | Step | Skill | Cost | GPU |
|---|------|-------|------|-----|
"""
    for i, subtask in enumerate(pipeline.get("subtasks", []), 1):
        skill = SKILL_CATALOG.get(subtask.get("skill_id", ""), {})
        gpu = "Yes" if subtask.get("gpu_required", False) else "No"
        readme += f"| {i} | {subtask.get('name', '')} | {subtask.get('skill_id', '')} | ${subtask.get('estimated_cost_usd', 0):.2f} | {gpu} |\n"

    readme += f"""
## Build & Run

```bash
# Build
colcon build --packages-select {pkg_name}
source install/setup.bash

# Run full pipeline
ros2 launch {pkg_name} pipeline.launch.py

# Run individual step
ros2 run {pkg_name} scene-creation_node
```

## Configuration

Edit `config/pipeline_params.yaml` to adjust parameters.

## Generated by

[SkillForge](https://github.com/skillforge) — Nebius Global AI Hackathon 2026
Pipeline hash: `{pipeline_hash}`
"""

    return {
        "package_name": pkg_name,
        "pipeline_hash": pipeline_hash,
        "pipeline_id": pipeline_id,
        "files": {
            "package.xml": pkg_xml,
            "CMakeLists.txt": cmakeLists,
            "pipeline.json": json.dumps(pipeline_export, indent=2),
            "launch/pipeline.launch.py": launch_py,
            "README.md": readme,
        },
        "metadata": pipeline_export["metadata"],
    }
