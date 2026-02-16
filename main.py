#!/usr/bin/env python3
"""
agentic_g4f_scaffold.py

CLI wrapper for the g4fagent library.
"""

from __future__ import annotations

import argparse
import textwrap
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from g4fagent import G4FManager
from g4fagent.constants import APP_ROOT, DEFAULT_CONFIG_REL_PATH
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
from tools import ToolResult, ToolRuntime


def run_tool(tools: ToolRuntime, call: Dict[str, Any]) -> ToolResult:
    tool = call.get("tool")
    args = call.get("args") or {}
    return tools.execute(str(tool), args)


def main() -> int:
    ap = argparse.ArgumentParser(description="Agentic G4F project scaffolder")
    ap.add_argument("--out", required=True, help="Output project directory")
    ap.add_argument("--model", default=None, help="Optional model name/string for g4f")
    ap.add_argument(
        "--config",
        default=DEFAULT_CONFIG_REL_PATH,
        help="Runtime config JSON path (relative to script directory by default)",
    )
    ap.add_argument("--zip", action="store_true", help="Also create a zip of the project folder")
    ap.add_argument(
        "--auto-accept",
        action="store_true",
        help="Skip per-file and tool-call approvals; write files immediately and run one final verification",
    )
    ap.add_argument("--temperature", type=float, default=None, help="Sampling temperature override for all stages")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manager = G4FManager.from_config(config_rel_path=args.config, base_dir=APP_ROOT)
    planning_stage, writing_stage = manager.default_stage_names()
    tools = ToolRuntime(out_dir)

    print_hr()
    print("🧪 Agentic G4F Scaffolder")
    print(f"Time: {now_iso()}")
    print(f"Output: {out_dir}")
    print(f"Config: {manager.runtime_cfg['_meta']['config_path']}")
    print(f"Agents dir: {manager.runtime_cfg['_meta']['agents_dir']}")
    print(f"Pipeline order: {planning_stage} -> {writing_stage}")
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
    print(f"Mode: {'auto-accept' if args.auto_accept else 'interactive'}")
    print_hr()

    user_prompt = prompt_multiline("Describe your coding project (requirements, constraints, stack, etc.).")
    if not user_prompt:
        print("No prompt provided. Exiting.")
        return 1

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
        )
        _, plan_obj = extract_plan_json(fix)
        if not plan_obj:
            print("Still no valid plan JSON. Exiting to avoid chaos.")
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
        return 2

    todo = plan_obj.get("todo", [])
    files = plan_obj.get("files", [])

    if not isinstance(files, list) or not files:
        print("No files in plan JSON. Exiting.")
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

    tools.execute("write_file", {"path": "PROJECT_PLAN.md", "content": plan_text_clean + "\n", "overwrite": True})
    tools.execute("write_file", {"path": "PROJECT_PLAN.json", "content": pretty_json(plan_obj) + "\n", "overwrite": True})

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

                res = run_tool(tools, tool_call)
                messages.append(msg("assistant", assistant))
                messages.append(msg("user", f"Tool result (ok={res.ok}):\n{clamp(res.output, 4000)}"))
                tool_steps += 1
                continue

            content_candidate = sanitize_generated_file_content(assistant)
            break

        if content_candidate is None:
            print("⚠️ Could not obtain file content. Skipping.")
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
                break

            act = ask_choice(
                f"Accept {rel}?",
                {"a": "accept/write", "f": "feedback/regenerate", "s": "skip", "q": "quit"},
                "a",
            )
            if act == "a":
                tools.execute("write_file", {"path": rel, "content": current_content, "overwrite": True})
                print(f"✅ Wrote {rel}")
                break
            if act == "s":
                print(f"⏭️ Skipped {rel}")
                break
            if act == "q":
                print("Stopping early.")
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
                    res = run_tool(tools, tool_call)
                    messages.append(msg("assistant", assistant))
                    messages.append(msg("user", f"Tool result (ok={res.ok}):\n{clamp(res.output, 4000)}"))
                    tool_steps += 1
                    continue
                content_candidate = sanitize_generated_file_content(assistant)
                break

            if content_candidate is None:
                print("⚠️ Regeneration failed; you can try feedback again or skip.")
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
        print_hr()

    print_hr()
    print("🏁 Done. Project tree:\n")
    print(show_tree(out_dir))
    print_hr()

    if args.zip:
        zip_path = make_zip(out_dir)
        print(f"📦 Zip created: {zip_path}")

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
