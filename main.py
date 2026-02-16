#!/usr/bin/env python3
"""
agentic_g4f_scaffold.py

CLI wrapper for the g4fagent library.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from g4fagent import (
    DATABASE_BACKENDS,
    G4FManager,
    Project,
    create_database,
    list_known_model_names_for_provider,
    list_known_provider_names,
    resolve_provider_name,
)
from g4fagent.api_server import run_api_server
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


def print_tool_call_console(tool_call: Dict[str, Any], *, auto_accept: bool, approval_needed: bool) -> None:
    print_hr()
    if approval_needed and auto_accept:
        print("🛠️ Auto-approved tool call:")
    elif approval_needed:
        print("🛠️ Model requests tool call (approval required):")
    else:
        print("🛠️ Model requests tool call (auto-executed):")
    print(pretty_json(tool_call))
    print_hr()


def read_json_dict(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def load_project_snapshot(path: Path) -> Optional[Dict[str, Any]]:
    return read_json_dict(path)


def project_needs_completion(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    state = snapshot.get("state")
    status = ""
    if isinstance(state, dict):
        status = str(state.get("status", "")).strip().lower()
    if status in {"completed", "completed_with_quality_failures"}:
        return False
    return True


def extract_saved_user_prompt(snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(snapshot, dict):
        return None
    accepted = snapshot.get("accepted_data")
    if not isinstance(accepted, dict):
        return None
    prompt = accepted.get("user_prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    return None


def load_resume_payload(out_dir: Path, snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    user_prompt = extract_saved_user_prompt(snapshot)
    if not user_prompt:
        return None

    accepted = snapshot.get("accepted_data")
    accepted = accepted if isinstance(accepted, dict) else {}
    plan_bucket = accepted.get("plan")
    plan_bucket = plan_bucket if isinstance(plan_bucket, dict) else {}

    plan_obj = read_json_dict(out_dir / "PROJECT_PLAN.json")
    if plan_obj is None:
        plan_json = plan_bucket.get("json")
        if isinstance(plan_json, dict):
            plan_obj = plan_json
    if not isinstance(plan_obj, dict):
        return None

    todo_raw = plan_obj.get("todo", [])
    todo = todo_raw if isinstance(todo_raw, list) else []

    files_raw = plan_obj.get("files", [])
    if not isinstance(files_raw, list) or not files_raw:
        return None

    files: List[Dict[str, Any]] = []
    expected_files: List[str] = []
    for item in files_raw:
        if not isinstance(item, dict):
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        try:
            rel = str(ensure_rel_path(path_value))
        except ValueError:
            continue
        normalized = dict(item)
        normalized["path"] = rel
        files.append(normalized)
        expected_files.append(rel)
    if not files:
        return None

    plan_text_clean = ""
    plan_md_path = out_dir / "PROJECT_PLAN.md"
    if plan_md_path.exists() and plan_md_path.is_file():
        plan_text_clean = plan_md_path.read_text(encoding="utf-8", errors="replace").strip()
    if not plan_text_clean:
        plan_text = plan_bucket.get("text")
        if isinstance(plan_text, str):
            plan_text_clean = plan_text.strip()

    return {
        "user_prompt": user_prompt,
        "plan_obj": plan_obj,
        "todo": todo,
        "files": files,
        "expected_files": expected_files,
        "plan_text_clean": plan_text_clean,
    }


def restore_project_from_snapshot(project: Project, snapshot: Dict[str, Any]) -> None:
    project.name = str(snapshot.get("name") or project.name)

    accepted = snapshot.get("accepted_data")
    if isinstance(accepted, dict):
        project.accepted_data = deepcopy(accepted)

    chat_history = snapshot.get("chat_history")
    if isinstance(chat_history, list):
        project.chat_history = deepcopy(chat_history)

    state = snapshot.get("state")
    if isinstance(state, dict):
        project.state = deepcopy(state)

    project.files = []
    for f in snapshot.get("files", []) if isinstance(snapshot.get("files"), list) else []:
        if not isinstance(f, dict):
            continue
        path_value = f.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        project.upsert_file(
            path=str(path_value),
            spec=f.get("spec"),
            content=f.get("content"),
            accepted=f.get("accepted"),
            status=f.get("status"),
            notes=f.get("notes"),
        )


def clear_directory_contents(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def is_file_marked_complete(project: Project, rel_path: str) -> bool:
    rel = str(rel_path)
    tracked = project.get_file(rel)
    if tracked is not None and tracked.accepted:
        return True
    accepted_files = project.accepted_data.get("accepted_files")
    if isinstance(accepted_files, list) and rel in accepted_files:
        return True
    accepted_file_contents = project.accepted_data.get("files")
    if isinstance(accepted_file_contents, dict) and rel in accepted_file_contents:
        return True
    return False


def append_accepted_file_once(project: Project, rel_path: str) -> None:
    rel = str(rel_path)
    accepted_files = project.accepted_data.get("accepted_files")
    if isinstance(accepted_files, list):
        if rel not in accepted_files:
            accepted_files.append(rel)
        return
    project.accept("accepted_files", [rel])


def resolve_existing_file_policy(skip_existing: bool, force: bool) -> str:
    if skip_existing and force:
        raise ValueError("--skip-existing and --force cannot be used together.")
    if skip_existing:
        return "skip"
    if force:
        return "force"
    return "prompt"


def persist_project_state(tools: ToolRuntime, project: Project) -> None:
    tools.execute(
        "write_file",
        {
            "path": "PROJECT_STATE.json",
            "content": pretty_json(project.to_dict()) + "\n",
            "overwrite": True,
        },
    )


def chat_with_model_retry(
    manager: G4FManager,
    messages: List[Dict[str, Any]],
    *,
    model: str,
    provider: Optional[str],
    create_kwargs: Optional[Dict[str, Any]],
    max_retries: int,
    stage_name: Optional[str],
    project: Optional[Project] = None,
    tools: Optional[ToolRuntime] = None,
    chat_delay_seconds: float = 0.0,
    chat_delay_state: Optional[Dict[str, Any]] = None,
    retry_no_selection_extra_delay_seconds: float = 5.0,
) -> Tuple[str, str]:
    current_model = str(model)
    delay = max(0.0, float(chat_delay_seconds))
    retry_extra_delay = max(0.0, float(retry_no_selection_extra_delay_seconds))
    blank_retry_count = 0
    while True:
        try:
            if delay > 0 and chat_delay_state is not None:
                now = time.monotonic()
                last_chat_time = chat_delay_state.get("last_chat_time")
                if isinstance(last_chat_time, (int, float)):
                    remaining = delay - (now - float(last_chat_time))
                    if remaining > 0:
                        time.sleep(remaining)
                if blank_retry_count > 0 and retry_extra_delay > 0:
                    time.sleep(retry_extra_delay * float(blank_retry_count))
                chat_delay_state["last_chat_time"] = time.monotonic()

            assistant = manager.chat(
                messages,
                model=current_model,
                provider=provider,
                create_kwargs=create_kwargs,
                max_retries=max_retries,
                stage_name=stage_name,
            )
            if delay > 0 and chat_delay_state is not None:
                # Reset delay after receiving a response so the next outbound
                # model request waits full delay from receive-time.
                chat_delay_state["last_chat_time"] = time.monotonic()
            return assistant, current_model
        except KeyboardInterrupt:
            raise
        except Exception as e:
            err_text = str(e)
            print_hr("-")
            print(
                "Model request failed "
                f"(stage={stage_name or 'unknown'}, provider={provider or 'auto'}, model={current_model})."
            )
            print(clamp(err_text, 3000))
            print("Type a different model and press Enter to retry.")
            print("Leave blank to retry the same model.")

            if project is not None:
                project.update_state(
                    {
                        "last_model_error": err_text,
                        "last_failed_model": current_model,
                        "last_failed_stage": stage_name,
                    }
                )
                if tools is not None:
                    persist_project_state(tools, project)

            next_model = input("Retry model> ").strip()
            if next_model:
                current_model = next_model
                blank_retry_count = 0
                if project is not None:
                    project.update_state(
                        {
                            "last_model_override": current_model,
                            "last_model_override_stage": stage_name,
                        }
                    )
                    if tools is not None:
                        persist_project_state(tools, project)
            else:
                blank_retry_count += 1


MUTATING_TOOLS = {"write_file", "apply_patch", "delete_file"}
ERROR_LINE_RE = re.compile(r"\berror\b|\bfailed\b|traceback", re.IGNORECASE)
WARNING_LINE_RE = re.compile(r"\bwarning\b", re.IGNORECASE)
ANSI_GREEN = "\x1b[32m"
ANSI_RED = "\x1b[31m"
ANSI_RESET = "\x1b[0m"


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


def use_ansi_colors() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(getattr(sys.stdout, "isatty", lambda: False)())
    except Exception:
        return False


def color_scan_status(status: str) -> str:
    if not use_ansi_colors():
        return status
    if status == "ok":
        return f"{ANSI_GREEN}{status}{ANSI_RESET}"
    return f"{ANSI_RED}{status}{ANSI_RESET}"


def provider_model_label(provider: Any, model: Any) -> str:
    provider_text = str(provider or "auto").strip() or "auto"
    model_text = str(model or "").strip()
    return f"{provider_text}/{model_text}"


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
    cli_provider: Optional[str],
    cli_temperature: Optional[float],
    auto_accept: bool,
    max_tool_steps: int,
    chat_delay_seconds: float = 0.0,
    chat_delay_state: Optional[Dict[str, Any]] = None,
    chat_retry_extra_delay_seconds: float = 5.0,
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
    model, provider, kwargs, retries = manager.build_stage_request(
        stage_name,
        cli_model,
        cli_provider,
        cli_temperature,
    )

    tool_steps = 0
    summary = ""
    while tool_steps < max_tool_steps:
        assistant, model = chat_with_model_retry(
            manager,
            messages,
            model=model,
            provider=provider,
            create_kwargs=kwargs,
            max_retries=retries,
            stage_name=stage_name,
            project=project,
            tools=tools,
            chat_delay_seconds=chat_delay_seconds,
            chat_delay_state=chat_delay_state,
            retry_no_selection_extra_delay_seconds=chat_retry_extra_delay_seconds,
        )
        tool_call = parse_tool_call(assistant)
        if tool_call:
            tool = str(tool_call.get("tool"))
            approval_needed = tool in MUTATING_TOOLS
            print_tool_call_console(tool_call, auto_accept=auto_accept, approval_needed=approval_needed)
            if approval_needed:
                if not auto_accept:
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


def print_model_scan_report(report: Dict[str, Any]) -> None:
    print_hr()
    print("Model scan report")
    print(
        "Summary: "
        f"total={report.get('total', 0)}, "
        f"ok={report.get('ok_count', 0)}, "
        f"failed={report.get('failed_count', 0)}, "
        f"no_response={report.get('no_response_count', 0)}, "
        f"errors={report.get('error_count', 0)}"
    )
    working = report.get("working_provider_models", []) or report.get("working_models", []) or []
    failing = report.get("failing_provider_models", []) or report.get("failing_models", []) or []
    if working:
        print(f"Working models ({len(working)}): {', '.join(working[:25])}")
    if failing:
        print(f"Failing models ({len(failing)}): {', '.join(failing[:25])}")

    for idx, item in enumerate(report.get("results", []), start=1):
        model = item.get("model", "")
        provider = item.get("provider", "auto")
        provider_model = item.get("provider_model") or provider_model_label(provider, model)
        status = item.get("status", "")
        elapsed = item.get("elapsed_seconds", 0)
        print(f"[{idx}] {provider_model} -> {color_scan_status(str(status))} ({elapsed}s)")
        err = item.get("error")
        preview = item.get("response_preview")
        if err:
            print(f"  error: {clamp(str(err), 300)}")
        elif preview:
            print(f"  preview: {clamp(str(preview), 300)}")
    print_hr()


def print_provider_list(providers: List[str]) -> None:
    print_hr("-")
    print("Available g4f providers")
    print(f"Total: {len(providers)}")
    for idx, provider_name in enumerate(providers, start=1):
        print(f"[{idx}] {provider_name}")
    print_hr("-")


def print_provider_model_list(provider_name: str, models: List[str]) -> None:
    print_hr("-")
    print(f"Models for provider: {provider_name}")
    print(f"Total: {len(models)}")
    for idx, model_name in enumerate(models, start=1):
        print(f"[{idx}] {model_name}")
    print_hr("-")


def resolve_config_location(config_value: str) -> Tuple[Path, str]:
    config_arg = Path(config_value)
    if config_value == DEFAULT_CONFIG_REL_PATH:
        return APP_ROOT, config_value
    if config_arg.is_absolute():
        return config_arg.parent, config_arg.name
    return Path.cwd(), config_value


def build_provider_model_scan_specs(
    *,
    requested_providers: List[str],
    requested_models: List[str],
) -> List[Dict[str, str]]:
    provider_inputs = [str(x).strip() for x in requested_providers if isinstance(x, str) and str(x).strip()]
    model_inputs: List[str] = []
    for value in requested_models:
        if not isinstance(value, str):
            continue
        model_name = value.strip()
        if not model_name:
            continue
        if model_name not in model_inputs:
            model_inputs.append(model_name)

    if provider_inputs:
        providers = provider_inputs
    else:
        providers = list_known_provider_names(include_meta=False)

    specs: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    explicit_provider_filter = bool(provider_inputs)

    for provider_name in providers:
        known_models = list_known_model_names_for_provider(provider_name)
        if model_inputs:
            if explicit_provider_filter:
                selected_models = list(model_inputs)
            else:
                selected_models = [m for m in model_inputs if m in set(known_models)]
        else:
            selected_models = list(known_models)

        for model_name in selected_models:
            key = (str(provider_name), str(model_name))
            if key in seen:
                continue
            seen.add(key)
            specs.append({"model": str(model_name), "provider": str(provider_name)})
    return specs


class ScanSkipController:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current_provider: Optional[str] = None
        self._current_model: Optional[str] = None
        self._skip_providers: set[str] = set()
        self._skip_models: set[Tuple[str, str]] = set()
        self._discard_current_providers: set[str] = set()
        self._discard_current_models: set[Tuple[str, str]] = set()

    def set_current(self, provider: str, model: str) -> None:
        with self._lock:
            self._current_provider = str(provider)
            self._current_model = str(model)

    def clear_current(self) -> None:
        with self._lock:
            self._current_provider = None
            self._current_model = None

    def request_skip_provider(self) -> Optional[str]:
        with self._lock:
            if not self._current_provider:
                return None
            provider = str(self._current_provider)
            self._skip_providers.add(provider)
            self._discard_current_providers.add(provider)
            return provider

    def request_skip_model(self) -> Optional[Tuple[str, str]]:
        with self._lock:
            if not self._current_provider or not self._current_model:
                return None
            pair = (str(self._current_provider), str(self._current_model))
            self._skip_models.add(pair)
            self._discard_current_models.add(pair)
            return pair

    def should_skip(self, provider: str, model: str) -> bool:
        key = (str(provider), str(model))
        with self._lock:
            return str(provider) in self._skip_providers or key in self._skip_models

    def should_discard_current_result(self, provider: str, model: str) -> bool:
        key = (str(provider), str(model))
        with self._lock:
            discard = False
            if str(provider) in self._discard_current_providers:
                self._discard_current_providers.discard(str(provider))
                discard = True
            if key in self._discard_current_models:
                self._discard_current_models.discard(key)
                discard = True
            return discard

    def skipped_providers(self) -> List[str]:
        with self._lock:
            return sorted(self._skip_providers)

    def skipped_model_pairs(self) -> List[Tuple[str, str]]:
        with self._lock:
            return sorted(self._skip_models)


def _start_scan_hotkey_listener(
    *,
    skip_controller: ScanSkipController,
    stop_event: threading.Event,
) -> Callable[[], None]:
    if os.name == "nt":
        try:
            import msvcrt  # type: ignore
        except Exception:
            return lambda: None

        def worker() -> None:
            while not stop_event.is_set():
                try:
                    if not msvcrt.kbhit():
                        time.sleep(0.05)
                        continue
                    key = msvcrt.getch()
                except Exception:
                    time.sleep(0.05)
                    continue
                if key == b"\x10":  # Ctrl+P
                    provider = skip_controller.request_skip_provider()
                    if provider:
                        print(f"\nSkip requested: provider '{provider}' (Ctrl+P)", flush=True)
                    else:
                        print("\nSkip provider ignored: no active provider/model.", flush=True)
                elif key in {b"\r", b"\x0d"}:  # Ctrl+M (same code as Enter)
                    model_pair = skip_controller.request_skip_model()
                    if model_pair:
                        print(
                            f"\nSkip requested: model '{model_pair[1]}' on provider '{model_pair[0]}' (Ctrl+M)",
                            flush=True,
                        )
                    else:
                        print("\nSkip model ignored: no active provider/model.", flush=True)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        def cleanup() -> None:
            stop_event.set()
            thread.join(timeout=0.3)

        return cleanup

    try:
        import select
        import termios
        import tty
    except Exception:
        return lambda: None
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return lambda: None

    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    except Exception:
        return lambda: None

    def worker() -> None:
        while not stop_event.is_set():
            try:
                ready, _, _ = select.select([fd], [], [], 0.1)
            except Exception:
                time.sleep(0.05)
                continue
            if not ready:
                continue
            try:
                ch = sys.stdin.read(1)
            except Exception:
                continue
            if ch == "\x10":
                provider = skip_controller.request_skip_provider()
                if provider:
                    print(f"\nSkip requested: provider '{provider}' (Ctrl+P)", flush=True)
                else:
                    print("\nSkip provider ignored: no active provider/model.", flush=True)
            elif ch in {"\r", "\n"}:
                model_pair = skip_controller.request_skip_model()
                if model_pair:
                    print(
                        f"\nSkip requested: model '{model_pair[1]}' on provider '{model_pair[0]}' (Ctrl+M)",
                        flush=True,
                    )
                else:
                    print("\nSkip model ignored: no active provider/model.", flush=True)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def cleanup() -> None:
        stop_event.set()
        thread.join(timeout=0.3)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            return

    return cleanup


def _build_incremental_scan_report(
    *,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    prompt: str,
    delay_seconds: float,
    max_workers: int,
    parallel: bool,
    stopped: bool,
    stop_reason: Optional[str],
    results: List[Dict[str, Any]],
    planned_total: int,
    skipped_providers: List[str],
    skipped_model_pairs: List[Tuple[str, str]],
) -> Dict[str, Any]:
    ordered_results = list(results)
    working = [r["model"] for r in ordered_results if r.get("ok")]
    failing = [r["model"] for r in ordered_results if not r.get("ok")]
    working_provider_models = [str(r.get("provider_model", "")) for r in ordered_results if r.get("ok")]
    failing_provider_models = [str(r.get("provider_model", "")) for r in ordered_results if not r.get("ok")]
    no_response = [r for r in ordered_results if str(r.get("status", "")) == "no_response"]
    errors = [r for r in ordered_results if str(r.get("status", "")) == "error"]

    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(max(0.0, float(duration_seconds)), 4),
        "prompt": prompt,
        "provider": None,
        "delay_seconds": delay_seconds,
        "parallel": bool(parallel),
        "max_workers": int(max_workers),
        "stopped": bool(stopped),
        "stop_reason": stop_reason,
        "planned_total": int(planned_total),
        "skipped_providers": list(skipped_providers),
        "skipped_provider_models": [f"{p}/{m}" for p, m in skipped_model_pairs],
        "total": len(ordered_results),
        "ok_count": len(working),
        "failed_count": len(failing),
        "no_response_count": len(no_response),
        "error_count": len(errors),
        "working_models": working,
        "failing_models": failing,
        "working_provider_models": working_provider_models,
        "failing_provider_models": failing_provider_models,
        "results": ordered_results,
    }


def _persist_scan_report(db: Any, run_id: str, report: Dict[str, Any]) -> None:
    if db is None:
        return
    db.set("scan_models", "last_run", report)
    db.set("scan_models", run_id, report)


def run_scan_models_command(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="g4fagent scan-models",
        description="Scan provider/model combinations and report working pairs.",
    )
    ap.add_argument(
        "--config",
        default=DEFAULT_CONFIG_REL_PATH,
        help=(
            "Runtime config JSON path. Default uses packaged assets; "
            "custom relative paths resolve from current working directory."
        ),
    )
    ap.add_argument(
        "--database",
        choices=list(DATABASE_BACKENDS),
        default=None,
        help="Optional persistence backend for runtime/project state.",
    )
    ap.add_argument(
        "--provider",
        "--scan-provider",
        action="append",
        default=[],
        help="Provider name to scan. Repeat to scan multiple providers.",
    )
    ap.add_argument(
        "--model",
        "--scan-model",
        action="append",
        default=[],
        help="Model alias/name to scan. Repeat to scan multiple specific models.",
    )
    ap.add_argument(
        "--prompt",
        "--scan-prompt",
        default="Reply with exactly: OK",
        help="Probe prompt used for model scanning.",
    )
    ap.add_argument(
        "--timeout",
        "--scan-timeout",
        type=float,
        default=30.0,
        help="Per-call timeout in seconds for model scans.",
    )
    ap.add_argument(
        "--delay",
        "--scan-delay",
        type=float,
        default=0.0,
        help="Delay between scan starts in seconds.",
    )
    ap.add_argument(
        "--parallel",
        "--scan-parallel",
        action="store_true",
        help="Request parallel scan mode (currently disabled when interactive skip controls are active).",
    )
    ap.add_argument(
        "--workers",
        "--scan-workers",
        type=int,
        default=4,
        help="Max workers for parallel model scans.",
    )
    ap.add_argument(
        "--output",
        "--scan-output",
        default=None,
        help="Optional file path to write scan JSON results.",
    )
    ap.add_argument("--list-providers", action="store_true", help="List valid g4f provider names and exit.")
    ap.add_argument(
        "--list-models-for-provider",
        default=None,
        help="List valid model aliases for the specified provider and exit.",
    )
    args = ap.parse_args(argv)

    if args.timeout is not None and args.timeout <= 0:
        print("--timeout must be > 0")
        return 2
    if args.workers <= 0:
        print("--workers must be > 0")
        return 2

    requested_providers: List[str] = []
    for raw_provider in args.provider or []:
        provider_text = str(raw_provider or "").strip()
        if not provider_text:
            continue
        resolved_provider = resolve_provider_name(provider_text)
        if resolved_provider is None:
            print(f"Unknown provider: {provider_text}")
            known = list_known_provider_names(include_meta=False)
            if known:
                print(f"Try one of: {', '.join(known[:30])}")
            return 2
        if resolved_provider not in requested_providers:
            requested_providers.append(resolved_provider)

    list_mode_used = False
    if args.list_providers:
        providers = list_known_provider_names(include_meta=False)
        print_provider_list(providers)
        list_mode_used = True

    if args.list_models_for_provider is not None:
        requested_provider = str(args.list_models_for_provider).strip()
        if not requested_provider:
            print("--list-models-for-provider requires a non-empty provider name.")
            return 2
        resolved_provider = resolve_provider_name(requested_provider)
        if resolved_provider is None:
            print(f"Unknown provider: {requested_provider}")
            known = list_known_provider_names(include_meta=False)
            if known:
                print(f"Try one of: {', '.join(known[:30])}")
            return 2
        provider_models = list_known_model_names_for_provider(resolved_provider)
        print_provider_model_list(resolved_provider, provider_models)
        list_mode_used = True

    if list_mode_used:
        return 0

    requested_models = [str(m).strip() for m in (args.model or []) if isinstance(m, str) and str(m).strip()]
    scan_specs = build_provider_model_scan_specs(
        requested_providers=requested_providers,
        requested_models=requested_models,
    )
    if not scan_specs:
        if requested_providers:
            print("No provider/model combinations matched your filters.")
        else:
            print("No provider/model combinations discovered to scan.")
        return 2

    config_base_dir, config_rel_path = resolve_config_location(str(args.config))
    manager = G4FManager.from_config(
        config_rel_path=config_rel_path,
        base_dir=config_base_dir,
        database=args.database,
        database_base_dir=Path.cwd(),
    )
    scan_db = manager.database or create_database("json", base_dir=Path.cwd())
    run_id = f"scan_{int(time.time() * 1000)}"
    started_at = now_iso()
    started_monotonic = time.monotonic()
    results: List[Dict[str, Any]] = []
    stop_reason: Optional[str] = None
    stream_state = {"count": 0, "stop_requested": False}
    skip_controller = ScanSkipController()
    hotkey_stop_event = threading.Event()
    hotkey_cleanup = _start_scan_hotkey_listener(skip_controller=skip_controller, stop_event=hotkey_stop_event)
    previous_sigint = signal.getsignal(signal.SIGINT)
    scan_delay_seconds = max(0.0, float(args.delay))
    effective_parallel = args.parallel

    def build_report_snapshot(*, status: str, stop_reason_value: Optional[str]) -> Dict[str, Any]:
        snapshot = _build_incremental_scan_report(
            started_at=started_at,
            finished_at=now_iso(),
            duration_seconds=round(max(0.0, time.monotonic() - started_monotonic), 4),
            prompt=str(args.prompt),
            delay_seconds=scan_delay_seconds,
            max_workers=int(args.workers),
            parallel=effective_parallel,
            stopped=bool(status != "running"),
            stop_reason=stop_reason_value,
            results=results,
            planned_total=len(scan_specs),
            skipped_providers=skip_controller.skipped_providers(),
            skipped_model_pairs=skip_controller.skipped_model_pairs(),
        )
        snapshot["run_id"] = run_id
        snapshot["status"] = status
        snapshot["filters"] = {
            "providers": list(requested_providers),
            "models": list(requested_models),
        }
        return snapshot

    def persist_report_snapshot(*, status: str, stop_reason_value: Optional[str]) -> None:
        snapshot = build_report_snapshot(status=status, stop_reason_value=stop_reason_value)
        _persist_scan_report(scan_db, run_id, snapshot)

    def request_scan_stop(reason: str) -> None:
        if stream_state["stop_requested"]:
            return
        stream_state["stop_requested"] = True
        print(f"\nStop requested ({reason}). Finishing current model request and returning partial results...")

    def handle_sigint(_signum: int, _frame: Any) -> None:
        if stream_state["stop_requested"]:
            raise KeyboardInterrupt
        request_scan_stop("Ctrl+C")

    print_hr()
    print("Scanning models...")
    print("Controls: Ctrl+C stop scan, Ctrl+P skip current provider, Ctrl+M skip current model.")
    signal.signal(signal.SIGINT, handle_sigint)
    persist_report_snapshot(status="running", stop_reason_value=None)
    try:
        next_scheduled_start = time.monotonic()
        for spec in scan_specs:
            provider_name = str(spec.get("provider", "")).strip()
            model_name = str(spec.get("model", "")).strip()
            if not provider_name or not model_name:
                continue
            provider_model = provider_model_label(provider_name, model_name)

            if stream_state["stop_requested"]:
                stop_reason = "stop_requested"
                break

            if skip_controller.should_skip(provider_name, model_name):
                print(f"[skip] {provider_model}")
                persist_report_snapshot(status="running", stop_reason_value=None)
                continue

            if scan_delay_seconds > 0:
                wait_seconds = next_scheduled_start - time.monotonic()
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                next_scheduled_start = max(next_scheduled_start, time.monotonic()) + scan_delay_seconds

            skip_controller.set_current(provider_name, model_name)
            single_result: Dict[str, Any]
            try:
                single_summary = manager.scan_models(
                    models=[{"model": model_name, "provider": provider_name}],
                    provider=None,
                    prompt=args.prompt,
                    create_kwargs={"timeout": args.timeout} if args.timeout is not None else {},
                    delay_seconds=0.0,
                    parallel=False,
                    max_workers=1,
                    on_result=None,
                    stop_requested=lambda: bool(stream_state["stop_requested"]),
                )
                single_report = single_summary.to_dict()
                single_items = list(single_report.get("results", []) or [])
                if single_items:
                    single_result = dict(single_items[0])
                else:
                    single_result = {
                        "model": model_name,
                        "provider": provider_name,
                        "provider_model": provider_model,
                        "ok": False,
                        "status": "error",
                        "elapsed_seconds": 0.0,
                        "response_preview": "",
                        "error": "No scan result was produced.",
                    }
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                single_result = {
                    "model": model_name,
                    "provider": provider_name,
                    "provider_model": provider_model,
                    "ok": False,
                    "status": "error",
                    "elapsed_seconds": 0.0,
                    "response_preview": "",
                    "error": str(exc),
                }
            finally:
                skip_controller.clear_current()

            if skip_controller.should_discard_current_result(provider_name, model_name):
                print(f"[skip-current] {provider_model}")
                persist_report_snapshot(status="running", stop_reason_value=None)
                continue

            results.append(single_result)
            stream_state["count"] += 1
            status = str(single_result.get("status", ""))
            elapsed = single_result.get("elapsed_seconds", 0)
            print(
                f"[{stream_state['count']}] {provider_model} -> {color_scan_status(status)} ({elapsed}s)",
                flush=True,
            )
            err = single_result.get("error")
            preview = single_result.get("response_preview")
            if err:
                print(f"  error: {clamp(str(err), 300)}", flush=True)
            elif preview:
                print(f"  preview: {clamp(str(preview), 300)}", flush=True)
            persist_report_snapshot(status="running", stop_reason_value=None)

            if stream_state["stop_requested"]:
                stop_reason = "stop_requested"
                break
    except KeyboardInterrupt:
        hotkey_cleanup()
        signal.signal(signal.SIGINT, previous_sigint)
        print("\nScan aborted immediately.")
        return 130
    finally:
        hotkey_cleanup()
        signal.signal(signal.SIGINT, previous_sigint)

    stopped = stop_reason is not None
    final_status = "stopped" if stopped else "completed"
    final_report = build_report_snapshot(status=final_status, stop_reason_value=stop_reason)
    _persist_scan_report(scan_db, run_id, final_report)

    if final_report.get("stopped"):
        print(
            f"Scan stopped early after {final_report.get('total', 0)} result(s) "
            f"(reason={final_report.get('stop_reason') or 'stop_requested'})."
        )
    print_model_scan_report(final_report)

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(pretty_json(final_report) + "\n", encoding="utf-8")
        print(f"Saved scan output to: {output_path}")
    return 0


def run_server_command(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="g4fagent server",
        description="Launch the G4FAgent Dev Platform REST API server",
    )
    ap.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    ap.add_argument("--base-path", default="/api/v1", help="Base API path prefix (default: /api/v1)")
    ap.add_argument(
        "--workspace",
        default=None,
        help="Workspace directory for API-managed project state/files (default: ./.g4fagent_api)",
    )
    ap.add_argument(
        "--config",
        default=DEFAULT_CONFIG_REL_PATH,
        help=(
            "Runtime config JSON path. Default uses packaged assets; "
            "custom relative paths resolve from current working directory."
        ),
    )
    ap.add_argument(
        "--tools-dir",
        action="append",
        default=[],
        help="Additional directory containing custom tool modules (*.py). Can be repeated.",
    )
    ap.add_argument(
        "--auth-disabled",
        action="store_true",
        help="Disable bearer auth checks (intended for local development only).",
    )
    ap.add_argument(
        "--api-key",
        default=os.getenv("G4FAGENT_API_KEY", "dev-api-key"),
        help="API key accepted by /auth/login when method=api_key (default: env G4FAGENT_API_KEY or dev-api-key).",
    )
    ap.add_argument(
        "--database",
        choices=list(DATABASE_BACKENDS),
        default=None,
        help="Optional persistence backend. When set, API state is loaded/saved through that backend.",
    )
    args = ap.parse_args(argv)

    if args.port < 1 or args.port > 65535:
        print("--port must be between 1 and 65535")
        return 2

    config_base_dir, config_rel_path = resolve_config_location(str(args.config))

    workspace_dir = Path(args.workspace).resolve() if args.workspace else (Path.cwd() / ".g4fagent_api").resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return run_api_server(
        host=str(args.host),
        port=int(args.port),
        base_path=str(args.base_path),
        workspace_dir=workspace_dir,
        config_rel_path=config_rel_path,
        config_base_dir=config_base_dir,
        tools_dirs=list(args.tools_dir or []),
        auth_disabled=bool(args.auth_disabled),
        api_key=str(args.api_key),
        database=args.database,
    )


def main() -> int:
    if len(sys.argv) > 1:
        cmd = str(sys.argv[1]).strip().lower()
        if cmd == "server":
            return run_server_command(sys.argv[2:])
        if cmd == "scan-models":
            return run_scan_models_command(sys.argv[2:])

    ap = argparse.ArgumentParser(description="Agentic G4F project scaffolder")
    ap.add_argument("--out", required=False, help="Output project directory")
    ap.add_argument("--model", default=None, help="Optional model name/string for g4f")
    ap.add_argument("--provider", default=None, help="Optional provider override for all non-scan stages.")
    ap.add_argument(
        "--config",
        default=DEFAULT_CONFIG_REL_PATH,
        help=(
            "Runtime config JSON path. Default uses packaged assets; "
            "custom relative paths resolve from current working directory."
        ),
    )
    ap.add_argument(
        "--database",
        choices=list(DATABASE_BACKENDS),
        default=None,
        help="Optional persistence backend for runtime/project state.",
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
        "--chat-delay",
        type=float,
        default=0.0,
        help="Minimum seconds between outbound non-scan model chat requests.",
    )
    ap.add_argument(
        "--chat-retry-extra-delay",
        type=float,
        default=5.0,
        help=(
            "Additional seconds per blank 'Retry model' input when --chat-delay > 0. "
            "Applied cumulatively for consecutive blank retries in the same step."
        ),
    )
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
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip planned files that already exist on disk without querying the model.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Allow overwrite flow for existing files without prompting for existing-file handling.",
    )
    args = ap.parse_args()

    try:
        existing_file_policy = resolve_existing_file_policy(
            skip_existing=bool(args.skip_existing),
            force=bool(args.force),
        )
    except ValueError as e:
        print(str(e))
        return 2

    if args.chat_delay is not None and args.chat_delay < 0:
        print("--chat-delay must be >= 0")
        return 2
    chat_delay_seconds = max(0.0, float(args.chat_delay or 0.0))
    if args.chat_retry_extra_delay is not None and args.chat_retry_extra_delay < 0:
        print("--chat-retry-extra-delay must be >= 0")
        return 2
    chat_retry_extra_delay_seconds = max(0.0, float(args.chat_retry_extra_delay or 0.0))
    chat_delay_state: Dict[str, Any] = {"last_chat_time": None}

    cli_provider_override: Optional[str] = None
    if args.provider is not None:
        requested_provider_override = str(args.provider).strip()
        if requested_provider_override:
            cli_provider_override = resolve_provider_name(requested_provider_override) or requested_provider_override

    config_base_dir, config_rel_path = resolve_config_location(str(args.config))

    manager = G4FManager.from_config(
        config_rel_path=config_rel_path,
        base_dir=config_base_dir,
        database=args.database,
        database_base_dir=Path.cwd(),
    )

    if not args.out:
        ap.error("--out is required.")

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "PROJECT_STATE.json"
    startup_mode = "new"
    startup_snapshot: Optional[Dict[str, Any]] = None
    startup_resume_payload: Optional[Dict[str, Any]] = None
    startup_seed_prompt: Optional[str] = None

    existing_snapshot = load_project_snapshot(state_path) if state_path.exists() else None
    if existing_snapshot and project_needs_completion(existing_snapshot):
        print_hr()
        saved_state = existing_snapshot.get("state")
        saved_status = str(saved_state.get("status", "unknown")) if isinstance(saved_state, dict) else "unknown"
        print(f"Detected incomplete PROJECT_STATE.json in {out_dir} (status={saved_status}).")
        action = ask_choice(
            "How would you like to proceed?",
            {
                "r": "resume incomplete build",
                "s": "restart from beginning with same prompt",
                "n": "clear output directory and start new project",
                "q": "quit",
            },
            "r",
        )
        if action == "q":
            print("Cancelled by user.")
            return 0
        if action == "n":
            clear_directory_contents(out_dir)
            startup_mode = "new"
            startup_snapshot = None
        elif action == "s":
            startup_mode = "restart"
            startup_seed_prompt = extract_saved_user_prompt(existing_snapshot)
            startup_snapshot = existing_snapshot
            if not startup_seed_prompt:
                print("Saved prompt not found in PROJECT_STATE.json; you will be prompted for a new prompt.")
        else:
            startup_mode = "resume"
            startup_snapshot = existing_snapshot
            startup_resume_payload = load_resume_payload(out_dir, existing_snapshot)
            if not startup_resume_payload:
                print("Resume data is incomplete. Falling back to restart with saved prompt.")
                startup_mode = "restart"
                startup_seed_prompt = extract_saved_user_prompt(existing_snapshot)
    elif existing_snapshot:
        print_hr()
        print("Existing PROJECT_STATE.json indicates the project is already complete.")
        print("Starting a new run will proceed with normal prompts and may overwrite generated files.")

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
    if startup_mode == "resume" and startup_snapshot is not None:
        restore_project_from_snapshot(project, startup_snapshot)
    else:
        project.name = out_dir.name
        project.accepted_data = {}
        project.chat_history = []
        project.state = {}
        project.files = []

    project.name = out_dir.name
    project.update_state(
        {
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
            "startup_mode": startup_mode,
            "chat_delay_seconds": chat_delay_seconds,
            "chat_retry_extra_delay_seconds": chat_retry_extra_delay_seconds,
            "existing_file_policy": existing_file_policy,
            "force": bool(args.force),
            "skip_existing": bool(args.skip_existing),
            "cli_provider_override": cli_provider_override,
        }
    )
    if startup_mode != "resume":
        project.update_state({"status": "initialized", "current_stage": None, "current_file": None})
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
        f"{cli_provider_override or manager.stage_provider_label(planning_stage) or 'auto'}"
    )
    print(
        f"{writing_stage} role/model/provider: "
        f"{manager.stage_role_name(writing_stage)} / "
        f"{manager.stage_model_label(writing_stage, args.model)} / "
        f"{cli_provider_override or manager.stage_provider_label(writing_stage) or 'auto'}"
    )
    if debug_stage:
        print(
            f"{debug_stage} role/model/provider: "
            f"{manager.stage_role_name(debug_stage)} / "
            f"{manager.stage_model_label(debug_stage, args.model)} / "
            f"{cli_provider_override or manager.stage_provider_label(debug_stage) or 'auto'}"
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
    print(f"Startup mode: {startup_mode}")
    print(f"Chat delay: {chat_delay_seconds}s")
    print(f"Chat retry extra delay: {chat_retry_extra_delay_seconds}s")
    print(f"Existing-file policy: {existing_file_policy}")
    print_hr()

    user_prompt = ""
    plan_text_clean = ""
    plan_obj: Optional[Dict[str, Any]] = None
    todo: List[Any] = []
    files: List[Dict[str, Any]] = []
    expected_files: List[str] = []

    if startup_mode == "resume" and startup_resume_payload is not None:
        user_prompt = str(startup_resume_payload.get("user_prompt", "")).strip()
        plan_obj = startup_resume_payload.get("plan_obj")
        todo = list(startup_resume_payload.get("todo", []))
        files = list(startup_resume_payload.get("files", []))
        expected_files = list(startup_resume_payload.get("expected_files", []))
        plan_text_clean = str(startup_resume_payload.get("plan_text_clean", "")).strip()
        if not user_prompt or not isinstance(plan_obj, dict) or not files:
            print("Resume data is incomplete. Exiting.")
            project.update_state({"status": "failed", "reason": "resume_data_invalid"})
            persist_project_state(tools, project)
            return 2
        if not plan_text_clean:
            plan_text_clean = pretty_json(plan_obj)

        print_hr()
        print("▶ Resuming incomplete build using saved PROJECT_STATE.json data.")
        print(f"Files in plan: {len(files)}")
        print_hr()

        project.accept("user_prompt", user_prompt)
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
        tools.execute(
            "write_file",
            {"path": "PROJECT_PLAN.json", "content": pretty_json(plan_obj) + "\n", "overwrite": True},
        )
        persist_project_state(tools, project)
    else:
        if startup_mode == "restart" and startup_seed_prompt:
            user_prompt = startup_seed_prompt
            print_hr()
            print("Restarting from the beginning using the saved prompt from PROJECT_STATE.json.")
            print_hr()
        else:
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
            cli_provider_override,
            args.temperature,
        )

        print_hr()
        print("🧠 Generating plan (TODO + layout + file specs)...")
        plan_text, plan_model = chat_with_model_retry(
            manager,
            plan_messages,
            model=plan_model,
            provider=plan_provider,
            create_kwargs=plan_kwargs,
            max_retries=plan_retries,
            stage_name=planning_stage,
            project=project,
            tools=tools,
            chat_delay_seconds=chat_delay_seconds,
            chat_delay_state=chat_delay_state,
            retry_no_selection_extra_delay_seconds=chat_retry_extra_delay_seconds,
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
            fix, plan_model = chat_with_model_retry(
                manager,
                fix_messages,
                model=plan_model,
                provider=plan_provider,
                create_kwargs=plan_kwargs,
                max_retries=plan_retries,
                stage_name=planning_stage,
                project=project,
                tools=tools,
                chat_delay_seconds=chat_delay_seconds,
                chat_delay_state=chat_delay_state,
                retry_no_selection_extra_delay_seconds=chat_retry_extra_delay_seconds,
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
            plan_text, plan_model = chat_with_model_retry(
                manager,
                amend_messages,
                model=plan_model,
                provider=plan_provider,
                create_kwargs=plan_kwargs,
                max_retries=plan_retries,
                stage_name=planning_stage,
                project=project,
                tools=tools,
                chat_delay_seconds=chat_delay_seconds,
                chat_delay_state=chat_delay_state,
                retry_no_selection_extra_delay_seconds=chat_retry_extra_delay_seconds,
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

        todo_raw = plan_obj.get("todo", [])
        todo = todo_raw if isinstance(todo_raw, list) else []
        files_raw = plan_obj.get("files", [])
        files = files_raw if isinstance(files_raw, list) else []

        if not files:
            print("No files in plan JSON. Exiting.")
            project.update_state({"status": "failed", "reason": "no_files_in_plan"})
            persist_project_state(tools, project)
            return 3

        expected_files = []
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
        tools.execute(
            "write_file",
            {"path": "PROJECT_PLAN.json", "content": pretty_json(plan_obj) + "\n", "overwrite": True},
        )
        persist_project_state(tools, project)

    print_hr()
    print("✍️ Writing files one-by-one with approval.")
    print(f"Existing-file handling: {existing_file_policy}")
    print("Tools available to the model: list_dir/read_file/write_file/apply_patch/delete_file")
    print_hr()

    write_model, write_provider, write_kwargs, write_retries = manager.build_stage_request(
        writing_stage,
        args.model,
        cli_provider_override,
        args.temperature,
    )

    for idx, f in enumerate(files, start=1):
        if not isinstance(f, dict):
            print(f"Skipping invalid file entry: {f}")
            continue
        path = f.get("path")
        spec = f.get("spec", "")
        if not path or not isinstance(path, str):
            print(f"Skipping invalid file entry: {f}")
            continue

        rel = str(ensure_rel_path(path))
        if startup_mode == "resume" and is_file_marked_complete(project, rel):
            print(f"⏩ Already completed in saved state, skipping: {rel}")
            project.set_state("files_processed", idx)
            persist_project_state(tools, project)
            continue
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

            if existing_file_policy == "skip":
                print(f"⏩ Keeping existing file due --skip-existing: {rel}")
                project.upsert_file(
                    rel,
                    content=existing,
                    accepted=True,
                    status="kept_existing",
                    notes="Kept existing file (--skip-existing)",
                )
                project.set_accepted_entry("files", rel, existing)
                append_accepted_file_once(project, rel)
                project.set_state("files_processed", idx)
                persist_project_state(tools, project)
                continue

            if existing_file_policy == "prompt":
                existing_choice = ask_choice(
                    f"Existing file found for {rel}. How should it be handled?",
                    {"o": "overwrite/generate", "k": "keep existing and skip", "q": "quit"},
                    "k",
                )
                if existing_choice == "q":
                    print("Stopping early.")
                    project.update_state({"status": "cancelled", "reason": "user_quit_on_existing_file_prompt"})
                    persist_project_state(tools, project)
                    if args.zip:
                        make_zip(out_dir)
                    return 0
                if existing_choice == "k":
                    print(f"⏩ Keeping existing file (user choice): {rel}")
                    project.upsert_file(
                        rel,
                        content=existing,
                        accepted=True,
                        status="kept_existing",
                        notes="Kept existing file (user choice)",
                    )
                    project.set_accepted_entry("files", rel, existing)
                    append_accepted_file_once(project, rel)
                    project.set_state("files_processed", idx)
                    persist_project_state(tools, project)
                    continue
            elif existing_file_policy == "force":
                print("⚠️ --force enabled: proceeding with overwrite/generation flow for existing file.")

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
            assistant, write_model = chat_with_model_retry(
                manager,
                messages,
                model=write_model,
                provider=write_provider,
                create_kwargs=write_kwargs,
                max_retries=write_retries,
                stage_name=writing_stage,
                project=project,
                tools=tools,
                chat_delay_seconds=chat_delay_seconds,
                chat_delay_state=chat_delay_state,
                retry_no_selection_extra_delay_seconds=chat_retry_extra_delay_seconds,
            )
            tool_call = parse_tool_call(assistant)
            if tool_call:
                tool = tool_call["tool"]
                approval_needed = tool in {"write_file", "apply_patch", "delete_file"}
                print_tool_call_console(tool_call, auto_accept=args.auto_accept, approval_needed=approval_needed)
                if approval_needed:
                    if not args.auto_accept:
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
                append_accepted_file_once(project, rel)
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
                append_accepted_file_once(project, rel)
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
                assistant, write_model = chat_with_model_retry(
                    manager,
                    messages,
                    model=write_model,
                    provider=write_provider,
                    create_kwargs=write_kwargs,
                    max_retries=write_retries,
                    stage_name=writing_stage,
                    project=project,
                    tools=tools,
                    chat_delay_seconds=chat_delay_seconds,
                    chat_delay_state=chat_delay_state,
                    retry_no_selection_extra_delay_seconds=chat_retry_extra_delay_seconds,
                )
                tool_call = parse_tool_call(assistant)
                if tool_call:
                    tool = tool_call["tool"]
                    approval_needed = tool in {"write_file", "apply_patch", "delete_file"}
                    print_tool_call_console(tool_call, auto_accept=args.auto_accept, approval_needed=approval_needed)
                    if approval_needed:
                        if not args.auto_accept:
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
                cli_provider=cli_provider_override,
                cli_temperature=args.temperature,
                auto_accept=args.auto_accept,
                max_tool_steps=debug_max_tool_steps,
                chat_delay_seconds=chat_delay_seconds,
                chat_delay_state=chat_delay_state,
                chat_retry_extra_delay_seconds=chat_retry_extra_delay_seconds,
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
