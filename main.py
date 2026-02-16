#!/usr/bin/env python3
"""
agentic_g4f_scaffold.py

CLI wrapper for the g4fagent library.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import textwrap
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from g4fagent import G4FManager, Project
from g4fagent.constants import APP_ROOT, DEFAULT_CONFIG_REL_PATH
from g4fagent.tools import ToolResult, ToolRuntime
from g4fagent.utils import (
    ask_choice,
    clamp,
    ensure_rel_path,
    extract_plan_json,
    final_verify_written_files,
    msg,
    now_iso,
    parse_tool_call,
    pretty_json,
    prompt_multiline,
    print_hr,
    sanitize_generated_file_content,
    show_tree,
    unified_diff_str,
)


def run_tool(tools: ToolRuntime, call: Dict[str, Any]) -> ToolResult:
    tool = call.get("tool")
    args = call.get("args") or {}
    return tools.execute(str(tool), args)


def persist_project_state(tools: ToolRuntime, project: Project) -> None:
    tools.execute(
        "write_file",
        {
            "path": "PROJECT_STATE.json",
            "content": pretty_json(project.to_dict()) + "\n",
            "overwrite": True,
        },
    )


MUTATING_TOOLS = {"write_file", "apply_patch", "delete_file"}
ERROR_LINE_RE = re.compile(r"\berror\b|\bfailed\b|traceback", re.IGNORECASE)
WARNING_LINE_RE = re.compile(r"\bwarning\b", re.IGNORECASE)


def find_debug_stage_name(manager: G4FManager) -> Optional[str]:
    for stage_name in manager.list_stages():
        try:
            role_name = manager.stage_role_name(stage_name)
        except Exception:
            continue
        if role_name == "DebugAgent":
            return stage_name
    for stage_name in manager.list_stages():
        if stage_name.lower() == "debug":
            return stage_name
    return None


def normalize_commands(raw: Optional[List[str]]) -> List[str]:
    cleaned: List[str] = []
    for cmd in raw or []:
        if not isinstance(cmd, str):
            continue
        stripped = cmd.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def extract_diagnostics(stdout: str, stderr: str) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    for line in (stdout + "\n" + stderr).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if WARNING_LINE_RE.search(stripped):
            warnings.append(stripped)
        if ERROR_LINE_RE.search(stripped):
            errors.append(stripped)
    return {"errors": errors, "warnings": warnings}


def run_quality_command(command: str, *, kind: str, cwd: Path) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        diagnostics = extract_diagnostics(stdout, stderr)
        if proc.returncode != 0 and not diagnostics["errors"]:
            diagnostics["errors"].append(f"{kind} command failed with exit code {proc.returncode}")
        return {
            "kind": kind,
            "command": command,
            "ok": proc.returncode == 0,
            "exit_code": int(proc.returncode),
            "stdout": stdout,
            "stderr": stderr,
            "errors": diagnostics["errors"],
            "warnings": diagnostics["warnings"],
        }
    except Exception as e:
        err = f"Failed to run {kind} command '{command}': {e}"
        return {
            "kind": kind,
            "command": command,
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": err,
            "errors": [err],
            "warnings": [],
        }


def run_quality_checks(out_dir: Path, lint_commands: List[str], test_commands: List[str]) -> Dict[str, Any]:
    reports: List[Dict[str, Any]] = []
    for command in lint_commands:
        reports.append(run_quality_command(command, kind="lint", cwd=out_dir))
    for command in test_commands:
        reports.append(run_quality_command(command, kind="test", cwd=out_dir))

    failed = [r for r in reports if not r["ok"]]
    total_errors = sum(len(r["errors"]) for r in reports)
    total_warnings = sum(len(r["warnings"]) for r in reports)
    return {
        "timestamp": now_iso(),
        "cwd": str(out_dir),
        "ran": {
            "lint": bool(lint_commands),
            "tests": bool(test_commands),
        },
        "commands": reports,
        "success": not failed,
        "totals": {
            "commands": len(reports),
            "failed": len(failed),
            "errors": total_errors,
            "warnings": total_warnings,
        },
    }


def print_quality_report(report: Dict[str, Any]) -> None:
    print_hr()
    print("🧪 Quality-check report")
    totals = report.get("totals", {})
    print(
        "Summary: "
        f"commands={totals.get('commands', 0)}, "
        f"failed={totals.get('failed', 0)}, "
        f"errors={totals.get('errors', 0)}, "
        f"warnings={totals.get('warnings', 0)}"
    )
    for idx, cmd in enumerate(report.get("commands", []), start=1):
        print_hr()
        print(f"[{idx}] {cmd.get('kind', '?').upper()} command: {cmd.get('command')}")
        print(f"Exit code: {cmd.get('exit_code')}")
        stdout = str(cmd.get("stdout", "") or "")
        stderr = str(cmd.get("stderr", "") or "")
        if stdout:
            print("stdout:")
            print(clamp(stdout, 12000))
        if stderr:
            print("stderr:")
            print(clamp(stderr, 12000))
        errors = cmd.get("errors", []) or []
        warnings = cmd.get("warnings", []) or []
        if errors:
            print("error lines:")
            print("\n".join([f"- {x}" for x in errors]))
        if warnings:
            print("warning lines:")
            print("\n".join([f"- {x}" for x in warnings]))
    print_hr()


def run_debug_stage_round(
    manager: G4FManager,
    stage_name: str,
    tools: ToolRuntime,
    project: Project,
    *,
    out_dir: Path,
    user_prompt: str,
    todo: List[Any],
    quality_report: Dict[str, Any],
    cli_model: Optional[str],
    cli_temperature: Optional[float],
    auto_accept: bool,
    max_tool_steps: int,
) -> Dict[str, Any]:
    debug_context = {
        "project_request": user_prompt,
        "todo": todo,
        "project_tree_so_far": show_tree(out_dir),
        "accepted_data_keys": sorted(project.accepted_data.keys()),
    }
    messages = manager.build_stage_messages(
        stage_name,
        {
            "project_context_json": pretty_json(debug_context),
            "quality_report_json": pretty_json(quality_report),
        },
    )
    model, provider, kwargs, retries = manager.build_stage_request(stage_name, cli_model, cli_temperature)

    tool_steps = 0
    summary = ""
    while tool_steps < max_tool_steps:
        assistant = manager.chat(
            messages,
            model=model,
            provider=provider,
            create_kwargs=kwargs,
            max_retries=retries,
            stage_name=stage_name,
        )
        tool_call = parse_tool_call(assistant)
        if tool_call:
            tool = str(tool_call.get("tool"))
            if tool in MUTATING_TOOLS:
                if auto_accept:
                    print("Auto-approved debug tool call:")
                    print(pretty_json(tool_call))
                else:
                    print_hr()
                    print("Debug model requests tool call (approval required):")
                    print(pretty_json(tool_call))
                    print_hr()
                    ok = ask_choice("Approve this debug tool call?", {"y": "yes", "n": "no"}, "y")
                    if ok != "y":
                        messages.append(msg("assistant", assistant))
                        messages.append(
                            msg(
                                "user",
                                "Tool call denied by user. Try another approach or summarize manual fixes.",
                            )
                        )
                        tool_steps += 1
                        continue
            project.append_accepted("tool_calls", tool_call)
            project.set_state("last_approved_tool", tool)
            res = run_tool(tools, tool_call)
            messages.append(msg("assistant", assistant))
            messages.append(msg("user", f"Tool result (ok={res.ok}):\n{clamp(res.output, 4000)}"))
            tool_steps += 1
            persist_project_state(tools, project)
            continue

        summary = assistant.strip()
        break

    if not summary:
        summary = f"Debug stage ended without summary after {tool_steps} tool step(s)."
    return {
        "summary": summary,
        "tool_steps": tool_steps,
        "model": model,
        "provider": provider,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Agentic G4F project scaffolder")
    ap.add_argument("--out", required=True, help="Output project directory")
    ap.add_argument("--model", default=None, help="Optional model name/string for g4f")
    ap.add_argument(
        "--config",
        default=DEFAULT_CONFIG_REL_PATH,
        help=(
            "Runtime config JSON path. Default uses packaged assets; "
            "custom relative paths resolve from current working directory."
        ),
    )
    ap.add_argument("--zip", action="store_true", help="Also create a zip of the project folder")
    ap.add_argument(
        "--auto-accept",
        action="store_true",
        help="Skip per-file and tool-call approvals; write files immediately and run one final verification",
    )
    ap.add_argument(
        "--tools-dir",
        action="append",
        default=[],
        help="Additional directory containing custom tool modules (*.py). Can be repeated.",
    )
    ap.add_argument("--temperature", type=float, default=None, help="Sampling temperature override for all stages")
    ap.add_argument(
        "--lint-cmd",
        action="append",
        default=None,
        help="Optional lint command to run after writing/debugging. Can be repeated.",
    )
    ap.add_argument(
        "--test-cmd",
        action="append",
        default=None,
        help="Optional test command to run after writing/debugging. Can be repeated.",
    )
    ap.add_argument("--skip-lint", action="store_true", help="Skip lint commands from config/CLI.")
    ap.add_argument("--skip-tests", action="store_true", help="Skip test commands from config/CLI.")
    ap.add_argument(
        "--max-debug-rounds",
        type=int,
        default=None,
        help="Max number of auto-debug rounds after failed quality checks.",
    )
    ap.add_argument(
        "--debug-max-tool-steps",
        type=int,
        default=None,
        help="Max tool-call turns allowed in each debug round.",
    )
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    config_arg = Path(args.config)
    if args.config == DEFAULT_CONFIG_REL_PATH:
        config_base_dir = APP_ROOT
        config_rel_path = args.config
    elif config_arg.is_absolute():
        config_base_dir = config_arg.parent
        config_rel_path = config_arg.name
    else:
        config_base_dir = Path.cwd()
        config_rel_path = args.config

    manager = G4FManager.from_config(config_rel_path=config_rel_path, base_dir=config_base_dir)
    planning_stage, writing_stage = manager.default_stage_names()
    debug_stage = find_debug_stage_name(manager)
    runtime_quality = dict((manager.runtime_cfg.get("quality_checks", {}) or {}))
    lint_commands = normalize_commands(args.lint_cmd if args.lint_cmd is not None else runtime_quality.get("lint_commands"))
    test_commands = normalize_commands(args.test_cmd if args.test_cmd is not None else runtime_quality.get("test_commands"))
    if args.skip_lint:
        lint_commands = []
    if args.skip_tests:
        test_commands = []
    quality_checks_enabled = bool(lint_commands or test_commands)
    max_debug_rounds = args.max_debug_rounds if args.max_debug_rounds is not None else runtime_quality.get(
        "max_debug_rounds", 2
    )
    debug_max_tool_steps = args.debug_max_tool_steps if args.debug_max_tool_steps is not None else runtime_quality.get(
        "debug_max_tool_steps", 10
    )
    try:
        max_debug_rounds = max(0, int(max_debug_rounds))
    except Exception:
        max_debug_rounds = 2
    try:
        debug_max_tool_steps = max(1, int(debug_max_tool_steps))
    except Exception:
        debug_max_tool_steps = 10
    try:
        tools = ToolRuntime(out_dir, extra_tool_dirs=args.tools_dir)
    except Exception as e:
        print(f"Failed to initialize tools: {e}")
        return 1
    project = manager.get_project()
    project.name = out_dir.name
    project.update_state(
        {
            "status": "initialized",
            "output_dir": str(out_dir),
            "config_path": str(manager.runtime_cfg["_meta"]["config_path"]),
            "agents_dir": str(manager.runtime_cfg["_meta"]["agents_dir"]),
            "planning_stage": planning_stage,
            "writing_stage": writing_stage,
            "debug_stage": debug_stage,
            "mode": "auto-accept" if args.auto_accept else "interactive",
            "extra_tools_dirs": list(args.tools_dir or []),
            "available_tools": tools.available_tools(),
            "loaded_tool_modules": tools.loaded_modules(),
            "quality_checks_enabled": quality_checks_enabled,
            "quality_commands": {"lint": lint_commands, "tests": test_commands},
            "quality_debug_settings": {
                "max_debug_rounds": max_debug_rounds,
                "debug_max_tool_steps": debug_max_tool_steps,
            },
            "current_stage": None,
            "current_file": None,
        }
    )
    persist_project_state(tools, project)

    print_hr()
    print("🧪 Agentic G4F Scaffolder")
    print(f"Time: {now_iso()}")
    print(f"Output: {out_dir}")
    print(f"Config: {manager.runtime_cfg['_meta']['config_path']}")
    print(f"Agents dir: {manager.runtime_cfg['_meta']['agents_dir']}")
    if args.tools_dir:
        print(f"Extra tools dirs: {', '.join(args.tools_dir)}")
        if tools.loaded_modules():
            print(f"Loaded external tool modules: {', '.join(tools.loaded_modules())}")
    print(f"Pipeline order: {' -> '.join(manager.list_stages())}")
    print(
        f"{planning_stage} role/model/provider: "
        f"{manager.stage_role_name(planning_stage)} / "
        f"{manager.stage_model_label(planning_stage, args.model)} / "
        f"{manager.stage_provider_label(planning_stage) or 'auto'}"
    )
    print(
        f"{writing_stage} role/model/provider: "
        f"{manager.stage_role_name(writing_stage)} / "
        f"{manager.stage_model_label(writing_stage, args.model)} / "
        f"{manager.stage_provider_label(writing_stage) or 'auto'}"
    )
    if debug_stage:
        print(
            f"{debug_stage} role/model/provider: "
            f"{manager.stage_role_name(debug_stage)} / "
            f"{manager.stage_model_label(debug_stage, args.model)} / "
            f"{manager.stage_provider_label(debug_stage) or 'auto'}"
        )
    if quality_checks_enabled:
        print("Quality checks: enabled")
        if lint_commands:
            print(f"Lint commands: {', '.join(lint_commands)}")
        if test_commands:
            print(f"Test commands: {', '.join(test_commands)}")
        print(f"Auto-debug rounds: {max_debug_rounds} (tool steps/round: {debug_max_tool_steps})")
    else:
        print("Quality checks: disabled (no lint/test commands configured)")
    print(f"Mode: {'auto-accept' if args.auto_accept else 'interactive'}")
    print_hr()

    user_prompt = prompt_multiline("Describe your coding project (requirements, constraints, stack, etc.).")
    if not user_prompt:
        print("No prompt provided. Exiting.")
        return 1
    project.accept("user_prompt", user_prompt)
    project.update_state({"status": "planning", "current_stage": planning_stage})
    persist_project_state(tools, project)

    plan_messages = manager.build_stage_messages(
        planning_stage,
        {
            "user_prompt": user_prompt,
        },
    )
    plan_model, plan_provider, plan_kwargs, plan_retries = manager.build_stage_request(
        planning_stage,
        args.model,
        args.temperature,
    )

    print_hr()
    print("🧠 Generating plan (TODO + layout + file specs)...")
    plan_text = manager.chat(
        plan_messages,
        model=plan_model,
        provider=plan_provider,
        create_kwargs=plan_kwargs,
        max_retries=plan_retries,
        stage_name=planning_stage,
    )
    plan_text_clean, plan_obj = extract_plan_json(plan_text)

    print_hr()
    print("📋 Proposed plan:\n")
    print(plan_text_clean)
    print_hr()

    if not plan_obj:
        print("⚠️ Could not parse <PLAN_JSON>. We'll continue, but file iteration needs JSON.")
        fix_messages = plan_messages + [
            msg("assistant", plan_text),
            msg("user", "Output ONLY the <PLAN_JSON> block again with valid JSON."),
        ]
        fix = manager.chat(
            fix_messages,
            model=plan_model,
            provider=plan_provider,
            create_kwargs=plan_kwargs,
            max_retries=plan_retries,
            stage_name=planning_stage,
        )
        _, plan_obj = extract_plan_json(fix)
        if not plan_obj:
            print("Still no valid plan JSON. Exiting to avoid chaos.")
            project.update_state({"status": "failed", "reason": "plan_json_missing"})
            persist_project_state(tools, project)
            return 2

    while True:
        choice = ask_choice(
            "Plan OK?",
            {"a": "accept", "f": "feedback/amend", "q": "quit"},
            "a",
        )
        if choice == "a":
            break
        if choice == "q":
            project.update_state({"status": "cancelled", "reason": "plan_rejected"})
            persist_project_state(tools, project)
            return 0
        fb = prompt_multiline("Enter feedback to amend the plan.")
        amend_messages = plan_messages + [
            msg("assistant", plan_text),
            msg("user", "Revise the plan based on this feedback and keep the same <PLAN_JSON> output format:\n\n" + fb),
        ]
        plan_text = manager.chat(
            amend_messages,
            model=plan_model,
            provider=plan_provider,
            create_kwargs=plan_kwargs,
            max_retries=plan_retries,
            stage_name=planning_stage,
        )
        plan_text_clean, plan_obj = extract_plan_json(plan_text)
        print_hr()
        print("🔁 Revised plan:\n")
        print(plan_text_clean)
        print_hr()
        if not plan_obj:
            print("⚠️ Revised plan missing valid <PLAN_JSON>. Try feedback again.")
            continue

    if plan_obj is None:
        print("No valid plan JSON available after approval loop. Exiting.")
        project.update_state({"status": "failed", "reason": "no_plan_json_after_approval"})
        persist_project_state(tools, project)
        return 2

    todo = plan_obj.get("todo", [])
    files = plan_obj.get("files", [])

    if not isinstance(files, list) or not files:
        print("No files in plan JSON. Exiting.")
        project.update_state({"status": "failed", "reason": "no_files_in_plan"})
        persist_project_state(tools, project)
        return 3

    expected_files: List[str] = []
    for f in files:
        if isinstance(f, dict):
            p = f.get("path")
            if isinstance(p, str) and p:
                try:
                    expected_files.append(str(ensure_rel_path(p)))
                except ValueError:
                    continue
    project.accept(
        "plan",
        {
            "text": plan_text_clean,
            "json": plan_obj,
            "todo": todo,
            "expected_files": expected_files,
        },
    )
    for f in files:
        if not isinstance(f, dict):
            continue
        p = f.get("path")
        if not isinstance(p, str) or not p:
            continue
        try:
            rel = str(ensure_rel_path(p))
        except ValueError:
            continue
        project.upsert_file(rel, spec=str(f.get("spec", "") or ""))
    project.update_state(
        {
            "status": "writing",
            "current_stage": writing_stage,
            "total_planned_files": len(expected_files),
        }
    )

    tools.execute("write_file", {"path": "PROJECT_PLAN.md", "content": plan_text_clean + "\n", "overwrite": True})
    tools.execute("write_file", {"path": "PROJECT_PLAN.json", "content": pretty_json(plan_obj) + "\n", "overwrite": True})
    persist_project_state(tools, project)

    print_hr()
    print("✍️ Writing files one-by-one with approval.")
    print("Tools available to the model: list_dir/read_file/write_file/apply_patch/delete_file")
    print_hr()

    write_model, write_provider, write_kwargs, write_retries = manager.build_stage_request(
        writing_stage,
        args.model,
        args.temperature,
    )

    for idx, f in enumerate(files, start=1):
        path = f.get("path")
        spec = f.get("spec", "")
        if not path or not isinstance(path, str):
            print(f"Skipping invalid file entry: {f}")
            continue

        rel = str(ensure_rel_path(path))
        abs_path = out_dir / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        project.update_state({"current_file": rel, "files_processed": idx - 1})
        project.upsert_file(rel, spec=str(spec or ""), status="in_progress")

        print_hr()
        print(f"🧩 File {idx}/{len(files)}: {rel}")
        if spec:
            print(textwrap.fill("Spec: " + spec, width=88))
        print_hr()

        existing: Optional[str] = None
        if abs_path.exists() and abs_path.is_file():
            existing = abs_path.read_text(encoding="utf-8", errors="replace")
            print("Existing file detected. (Model should prefer apply_patch for changes.)")
            print("Preview:")
            print(clamp(existing, 800))
            print_hr()

        file_context = {
            "project_request": user_prompt,
            "todo": todo,
            "file_path": rel,
            "file_spec": spec,
            "project_tree_so_far": show_tree(out_dir),
        }

        messages = manager.build_stage_messages(
            writing_stage,
            {
                "project_context_json": pretty_json(file_context),
                "file_path": rel,
                "project_request": user_prompt,
                "todo_json": pretty_json(todo),
            },
        )

        content_candidate: Optional[str] = None
        tool_steps = 0
        MAX_TOOL_STEPS = 8

        while tool_steps < MAX_TOOL_STEPS:
            assistant = manager.chat(
                messages,
                model=write_model,
                provider=write_provider,
                create_kwargs=write_kwargs,
                max_retries=write_retries,
                stage_name=writing_stage,
            )
            tool_call = parse_tool_call(assistant)
            if tool_call:
                tool = tool_call["tool"]
                approval_needed = tool in {"write_file", "apply_patch", "delete_file"}
                if approval_needed:
                    if args.auto_accept:
                        print("🛠️ Auto-approved tool call:")
                        print(pretty_json(tool_call))
                    else:
                        print_hr()
                        print("🛠️ Model requests tool call (approval required):")
                        print(pretty_json(tool_call))
                        print_hr()
                        ok = ask_choice("Approve this tool call?", {"y": "yes", "n": "no"}, "y")
                        if ok != "y":
                            messages.append(msg("assistant", assistant))
                            messages.append(msg("user", "Tool call denied by user. Propose an alternative (or ask for clarification)."))
                            tool_steps += 1
                            continue

                project.append_accepted("tool_calls", tool_call)
                project.set_state("last_approved_tool", tool)
                res = run_tool(tools, tool_call)
                messages.append(msg("assistant", assistant))
                messages.append(msg("user", f"Tool result (ok={res.ok}):\n{clamp(res.output, 4000)}"))
                tool_steps += 1
                persist_project_state(tools, project)
                continue

            content_candidate = sanitize_generated_file_content(assistant)
            break

        if content_candidate is None:
            print("⚠️ Could not obtain file content. Skipping.")
            project.upsert_file(rel, status="skipped", notes="No content candidate produced")
            project.set_state("files_processed", idx)
            persist_project_state(tools, project)
            continue

        print_hr()
        if existing is not None:
            diff = unified_diff_str(existing, content_candidate, rel)
            print("🔍 Proposed changes (unified diff):\n")
            print(diff if diff.strip() else "(no changes)")
        else:
            print("📝 Proposed file content:\n")
            print(clamp(content_candidate, 4000))
            print("\n(…content may be truncated in display; full content will be written if accepted.)")
        print_hr()

        while True:
            current_content = content_candidate
            if current_content is None:
                print("⚠️ No content available for this file yet. Try regenerate or skip.")
                continue

            if args.auto_accept:
                tools.execute("write_file", {"path": rel, "content": current_content, "overwrite": True})
                print(f"✅ Wrote {rel} (auto-accept)")
                project.upsert_file(rel, content=current_content, accepted=True, status="written")
                project.set_accepted_entry("files", rel, current_content)
                project.append_accepted("accepted_files", rel)
                project.set_state("files_processed", idx)
                persist_project_state(tools, project)
                break

            act = ask_choice(
                f"Accept {rel}?",
                {"a": "accept/write", "f": "feedback/regenerate", "s": "skip", "q": "quit"},
                "a",
            )
            if act == "a":
                tools.execute("write_file", {"path": rel, "content": current_content, "overwrite": True})
                print(f"✅ Wrote {rel}")
                project.upsert_file(rel, content=current_content, accepted=True, status="written")
                project.set_accepted_entry("files", rel, current_content)
                project.append_accepted("accepted_files", rel)
                project.set_state("files_processed", idx)
                persist_project_state(tools, project)
                break
            if act == "s":
                print(f"⏭️ Skipped {rel}")
                project.upsert_file(rel, accepted=False, status="skipped", notes="Skipped by user")
                project.set_state("files_processed", idx)
                persist_project_state(tools, project)
                break
            if act == "q":
                print("Stopping early.")
                project.update_state({"status": "cancelled", "reason": "user_quit_during_writing"})
                persist_project_state(tools, project)
                if args.zip:
                    make_zip(out_dir)
                return 0

            fb = prompt_multiline(f"Feedback for {rel} (what to change).")
            regen_msgs = messages + [
                msg("assistant", current_content),
                msg("user", "Revise the file based on this feedback. If the file already exists, prefer apply_patch.\n\n" + fb),
            ]
            messages = regen_msgs
            content_candidate = None
            tool_steps = 0

            while tool_steps < MAX_TOOL_STEPS:
                assistant = manager.chat(
                    messages,
                    model=write_model,
                    provider=write_provider,
                    create_kwargs=write_kwargs,
                    max_retries=write_retries,
                    stage_name=writing_stage,
                )
                tool_call = parse_tool_call(assistant)
                if tool_call:
                    tool = tool_call["tool"]
                    approval_needed = tool in {"write_file", "apply_patch", "delete_file"}
                    if approval_needed:
                        if args.auto_accept:
                            print("🛠️ Auto-approved tool call:")
                            print(pretty_json(tool_call))
                        else:
                            print_hr()
                            print("🛠️ Model requests tool call (approval required):")
                            print(pretty_json(tool_call))
                            print_hr()
                            ok = ask_choice("Approve this tool call?", {"y": "yes", "n": "no"}, "y")
                            if ok != "y":
                                messages.append(msg("assistant", assistant))
                                messages.append(msg("user", "Tool call denied by user. Provide another approach."))
                                tool_steps += 1
                                continue
                    project.append_accepted("tool_calls", tool_call)
                    project.set_state("last_approved_tool", tool)
                    res = run_tool(tools, tool_call)
                    messages.append(msg("assistant", assistant))
                    messages.append(msg("user", f"Tool result (ok={res.ok}):\n{clamp(res.output, 4000)}"))
                    tool_steps += 1
                    persist_project_state(tools, project)
                    continue
                content_candidate = sanitize_generated_file_content(assistant)
                break

            if content_candidate is None:
                print("⚠️ Regeneration failed; you can try feedback again or skip.")
                project.upsert_file(rel, status="retry_needed", notes="Regeneration failed")
                persist_project_state(tools, project)
                continue

            existing = abs_path.read_text(encoding="utf-8", errors="replace") if abs_path.exists() else None
            print_hr()
            if existing is not None:
                diff = unified_diff_str(existing, content_candidate, rel)
                print("🔍 Revised proposal (unified diff vs current on disk):\n")
                print(diff if diff.strip() else "(no changes)")
            else:
                print("📝 Revised file content:\n")
                print(clamp(content_candidate, 4000))
            print_hr()

    if args.auto_accept:
        print_hr()
        print("🔎 Final verification (auto-accept mode):")
        ok, verification_report = final_verify_written_files(out_dir, expected_files)
        print(verification_report)
        if not ok:
            print("⚠️ Final verification failed. Review issues above.")
        project.accept("final_verification", {"ok": ok, "report": verification_report})
        project.set_state("verification_ok", bool(ok))
        persist_project_state(tools, project)
        print_hr()

    quality_passed = True
    if quality_checks_enabled:
        print_hr()
        print("🔎 Running optional lint/test quality checks...")
        project.update_state({"status": "quality_checks", "current_stage": None, "quality_checks_round": 0})
        persist_project_state(tools, project)

        debug_round = 0
        while True:
            quality_report = run_quality_checks(out_dir, lint_commands=lint_commands, test_commands=test_commands)
            quality_report["quality_round"] = debug_round + 1
            print_quality_report(quality_report)

            project.append_accepted("quality_checks_history", quality_report)
            project.accept("quality_checks_last", quality_report)
            project.update_state(
                {
                    "quality_checks_round": debug_round + 1,
                    "quality_checks_last_success": bool(quality_report.get("success")),
                    "quality_checks_last_totals": dict((quality_report.get("totals", {}) or {})),
                }
            )
            persist_project_state(tools, project)

            if quality_report.get("success"):
                print("✅ Quality checks passed.")
                quality_passed = True
                break

            quality_passed = False
            print("⚠️ Quality checks failed.")
            if not debug_stage:
                print("No debug stage configured, so no automatic fix round will run.")
                break
            if debug_round >= max_debug_rounds:
                print(f"Reached max debug rounds ({max_debug_rounds}).")
                break

            debug_round += 1
            print_hr()
            print(f"🐞 Debug round {debug_round}/{max_debug_rounds}")
            project.update_state({"status": "debugging", "current_stage": debug_stage})
            persist_project_state(tools, project)

            debug_result = run_debug_stage_round(
                manager,
                stage_name=debug_stage,
                tools=tools,
                project=project,
                out_dir=out_dir,
                user_prompt=user_prompt,
                todo=todo,
                quality_report=quality_report,
                cli_model=args.model,
                cli_temperature=args.temperature,
                auto_accept=args.auto_accept,
                max_tool_steps=debug_max_tool_steps,
            )
            project.append_accepted(
                "debug_rounds",
                {
                    "round": debug_round,
                    "quality_report": quality_report,
                    "debug_result": debug_result,
                },
            )
            project.update_state(
                {
                    "last_debug_round": debug_round,
                    "last_debug_summary": debug_result.get("summary", ""),
                    "last_debug_tool_steps": debug_result.get("tool_steps", 0),
                }
            )
            persist_project_state(tools, project)
            print("Debug model summary:")
            print(clamp(str(debug_result.get("summary", "")), 4000))
            print_hr()

    print_hr()
    print("🏁 Done. Project tree:\n")
    print(show_tree(out_dir))
    print_hr()

    if args.zip:
        zip_path = make_zip(out_dir)
        print(f"📦 Zip created: {zip_path}")
        project.update_state({"zip_path": str(zip_path)})

    final_status = "completed"
    if quality_checks_enabled and not quality_passed:
        final_status = "completed_with_quality_failures"
    project.update_state({"status": final_status, "current_stage": None, "current_file": None})
    persist_project_state(tools, project)
    print("✨ Finished.")
    return 0


def make_zip(out_dir: Path) -> Path:
    zip_path = out_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in out_dir.rglob("*"):
            if p.is_dir():
                continue
            zf.write(p, arcname=str(p.relative_to(out_dir)))
    return zip_path


if __name__ == "__main__":
    raise SystemExit(main())
