# G4FAgent

Agentic scaffolding toolkit built on top of `g4f`.

## What this repo contains

- `g4fagent/`: importable SDK package (`G4FManager`, `Pipeline`, `Stage`, `Agent`)
- `main.py`: CLI wrapper built on the SDK
- `tools/`: local tool runtime and file-tool implementations
- `config.json` + `agents/*.json`: runtime agent/pipeline configuration

## Install

```bash
pip install -e .
```

## Run the CLI

```bash
python main.py --out ./my_project
python main.py --out ./my_project --config ./config.json
python main.py --out ./my_project --model gpt-4o-mini --temperature 0.2
```

## SDK quick start

```python
from g4fagent import G4FManager
from g4fagent.constants import APP_ROOT

manager = G4FManager.from_config(config_rel_path="config.json", base_dir=APP_ROOT)
print(manager.list_agents())
print(manager.list_stages())
```

## Notes

- The CLI and SDK both read stage/role definitions from JSON files.
- You can customize providers/models/prompts per stage through config overrides.
