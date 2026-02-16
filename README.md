# G4FAgent

Agentic scaffolding toolkit built on top of `g4f`.

## What this repo contains

- `g4fagent/`: importable SDK package (`G4FManager`, `Pipeline`, `Stage`, `Agent`)
- `main.py`: CLI wrapper built on the SDK
- `g4fagent/tools/`: built-in tool runtime and default tool implementations
- `config.json` + `agents/*.json`: runtime agent/pipeline configuration

## Install

```bash
pip install -e .
# or from PyPI once published:
# pip install g4fagent
```

## Run the CLI

```bash
g4fagent --out ./my_project
g4fagent --out ./my_project --config ./config.json
g4fagent --out ./my_project --model gpt-4o-mini --temperature 0.2
g4fagent --out ./my_project --tools-dir ./custom_tools
g4fagent scan-models
g4fagent scan-models --provider OpenaiChat --parallel --workers 6
g4fagent --out ./my_project --lint-cmd "ruff check ." --test-cmd "python -m unittest discover -s tests -p test_offline*.py"
```

`scan-models` writes rolling results to the configured database after each model result (`scan_models.last_run`) so partial progress survives abrupt exits.
While a scan is running: `Ctrl+C` stops, `Ctrl+P` skips the current provider, and `Ctrl+M` skips the current model.

If lint/test commands fail and a `debug` stage is configured, the CLI can auto-run debug rounds that feed stdout/stderr/errors/warnings back to `DebugAgent` for fixes.


## Run tests

Interactive test menus are available for offline-only, online-only, or both:

```bat
run_tests.bat
```

```bash
bash ./run_tests.sh
```

The suite now includes MCP-tool tests:
- Offline: direct `ToolRuntime` execution of MCP-style tools
- Online: model-generated MCP tool call envelope + runtime execution

## Build and publish

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

For a dry run, upload to TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

## SDK quick start

```python
from g4fagent import G4FManager
from g4fagent.constants import APP_ROOT

manager = G4FManager.from_config(config_rel_path="config.json", base_dir=APP_ROOT)
print(manager.list_agents())
print(manager.list_stages())

# optional persistence backend
manager_with_db = G4FManager.from_config(
    config_rel_path="config.json",
    base_dir=APP_ROOT,
    database="json",
)
```

## Scan available models

```python
from g4fagent import scan_models

summary = scan_models(
    parallel=True,
    max_workers=4,
    delay_seconds=0.5,
    create_kwargs={"timeout": 30},
)
print(summary.to_dict()["working_models"])
```

## Auto-detect verifier binaries

```python
from g4fagent import detect_verification_program_paths

detected = detect_verification_program_paths()
print(detected["lint_command_suggestions"][:3])
print(detected["test_command_suggestions"][:3])
```

This checks `PATH` plus common OS-specific locations (for example Windows Python installs such as `C:\\Python*\\python.exe`) to help populate lint/test config commands.

## Notes

- The CLI and SDK both read stage/role definitions from JSON files.
- You can customize providers/models/prompts per stage through config overrides.
- Built-in tools are loaded from `g4fagent.tools` by default.
- Add custom tools by passing one or more `--tools-dir` values.
- Custom tool files should import `ToolCategory` and `tool` from `g4fagent.tools`.
