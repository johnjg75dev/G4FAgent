"""Core SDK primitives for managing agents, stages, pipelines, and G4F calls.

Inputs:
- Module imports and runtime configuration objects passed into public APIs.
Output:
- Class and function APIs for agent/stage/pipeline orchestration and chat execution.
Example:
```python
from g4fagent import G4FManager
manager = G4FManager.from_config()
```
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import load_runtime_config, resolve_pipeline_stages
from .constants import APP_ROOT, DEFAULT_CONFIG_REL_PATH, G4F_SUPPORTED_CHAT_PARAMS
from .utils import (
    clamp,
    deep_merge_dict,
    detect_verification_program_paths as detect_verification_program_paths_util,
    format_template,
    msg,
    now_iso,
    pretty_json,
)

try:
    import g4f
    from g4f.typing import Messages
except Exception as e:
    raise ImportError("Failed to import g4f. Install with: pip install g4f") from e


@dataclass
class LLMConfig:
    """Runtime configuration for low-level chat execution behavior.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - LLMConfig: A configured `LLMConfig` instance.
    Example:
    ```python
    obj = LLMConfig(...)
    ```
    """

    max_retries: int = 2
    log_requests: bool = True


def resolve_model_name(name: Optional[str]) -> str:
    """Resolve a model alias to a concrete g4f model name.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = resolve_model_name(...)
    ```
    """
    if name and name != "default":
        return str(name)
    return getattr(g4f.models, "default", None) or "gpt-3.5-turbo"


def enforce_strict_json_object_response_format(response_format: Any) -> Any:
    """Normalize JSON response formats to strict object-shaped JSON schema.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = enforce_strict_json_object_response_format(...)
    ```
    """
    if response_format is None:
        return None

    if isinstance(response_format, str):
        if response_format not in {"json", "json_object"}:
            return response_format
        response_format = {"type": response_format}

    if not isinstance(response_format, dict):
        return response_format

    rf_type = str(response_format.get("type", "")).strip()
    if rf_type not in {"json", "json_object", "json_schema"}:
        return response_format

    json_schema: Dict[str, Any] = {}
    if rf_type == "json_schema":
        existing_json_schema = response_format.get("json_schema")
        if isinstance(existing_json_schema, dict):
            json_schema = dict(existing_json_schema)

    schema = json_schema.get("schema")
    if not isinstance(schema, dict):
        schema = {}
    else:
        schema = dict(schema)

    # Force object output so downstream code can always parse a JSON object.
    schema["type"] = "object"
    schema.setdefault("additionalProperties", True)

    json_schema["name"] = str(json_schema.get("name") or "response")
    json_schema["strict"] = True
    json_schema["schema"] = schema

    return {
        "type": "json_schema",
        "json_schema": json_schema,
    }


def merge_prompt_media_kwargs(
    create_kwargs: Optional[Dict[str, Any]],
    *,
    image: Any = None,
    image_name: Optional[str] = None,
    images: Any = None,
    media: Any = None,
) -> Dict[str, Any]:
    """Merge image/media prompt inputs into g4f create kwargs.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = merge_prompt_media_kwargs(...)
    ```
    """
    kwargs = dict(create_kwargs or {})
    if media is not None:
        kwargs["media"] = media
        kwargs.pop("image", None)
        kwargs.pop("image_name", None)
        kwargs.pop("images", None)
        return kwargs

    if image is not None:
        kwargs["image"] = image
        if image_name is not None:
            kwargs["image_name"] = image_name
        kwargs.pop("media", None)
        kwargs.pop("images", None)
        return kwargs

    if images is not None:
        kwargs["images"] = images
        kwargs.pop("media", None)
        kwargs.pop("image", None)
        kwargs.pop("image_name", None)
        return kwargs

    if image_name is not None and kwargs.get("image") is not None:
        kwargs["image_name"] = image_name

    return kwargs


def _coerce_chat_response_text(resp: Any) -> str:
    """Extract a text payload from supported g4f response shapes.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = _coerce_chat_response_text(...)
    ```
    """
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        try:
            return str(resp["choices"][0]["message"]["content"])
        except Exception:
            return str(resp)
    return str(resp)


def list_known_model_names(include_defaults: bool = True) -> List[str]:
    """Return model aliases discovered from `g4f.models`.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = list_known_model_names(...)
    ```
    """
    model_cls = getattr(g4f.models, "Model", None)
    if model_cls is None:
        return []

    names: List[str] = []
    for attr_name, attr_value in vars(g4f.models).items():
        if attr_name.startswith("_"):
            continue
        if not isinstance(attr_value, model_cls):
            continue
        if not include_defaults and attr_name.startswith("default"):
            continue
        names.append(attr_name)
    return sorted(names)


@dataclass
class ModelScanResult:
    """Represents one model probe outcome from a model-availability scan.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - ModelScanResult: A configured `ModelScanResult` instance.
    Example:
    ```python
    obj = ModelScanResult(...)
    ```
    """

    model: str
    ok: bool
    status: str
    elapsed_seconds: float
    response_preview: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the scan result into a plain dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        return {
            "model": self.model,
            "ok": self.ok,
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds,
            "response_preview": self.response_preview,
            "error": self.error,
        }


@dataclass
class ModelScanSummary:
    """Aggregated output from a full model-availability scan run.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - ModelScanSummary: A configured `ModelScanSummary` instance.
    Example:
    ```python
    obj = ModelScanSummary(...)
    ```
    """

    started_at: str
    finished_at: str
    duration_seconds: float
    prompt: str
    provider: Optional[str]
    delay_seconds: float
    parallel: bool
    max_workers: int
    results: List[ModelScanResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the scan summary into a plain dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        working = [r.model for r in self.results if r.ok]
        failing = [r.model for r in self.results if not r.ok]
        no_response = [r for r in self.results if r.status == "no_response"]
        errors = [r for r in self.results if r.status == "error"]
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "prompt": self.prompt,
            "provider": self.provider,
            "delay_seconds": self.delay_seconds,
            "parallel": self.parallel,
            "max_workers": self.max_workers,
            "total": len(self.results),
            "ok_count": len(working),
            "failed_count": len(failing),
            "no_response_count": len(no_response),
            "error_count": len(errors),
            "working_models": working,
            "failing_models": failing,
            "results": [r.to_dict() for r in self.results],
        }


def _resolve_scan_target(model: Any) -> Tuple[str, Any]:
    if isinstance(model, str):
        model_name = model.strip()
        if not model_name:
            return "", ""
        resolved = getattr(g4f.models, model_name, None)
        if resolved is None:
            return model_name, model_name
        return model_name, resolved

    label = getattr(model, "name", None)
    if isinstance(label, str) and label.strip():
        return label, model
    return str(model), model


def scan_models(
    models: Optional[List[Any]] = None,
    *,
    provider: Optional[str] = None,
    prompt: str = "Reply with exactly: OK",
    create_kwargs: Optional[Dict[str, Any]] = None,
    delay_seconds: float = 0.0,
    parallel: bool = False,
    max_workers: int = 4,
    response_preview_chars: int = 180,
) -> ModelScanSummary:
    """Probe models with a lightweight prompt and classify success/failure.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = scan_models(...)
    ```
    """
    raw_targets = list(models) if models is not None else list_known_model_names(include_defaults=True)
    targets: List[Tuple[int, str, Any]] = []
    for raw in raw_targets:
        label, target = _resolve_scan_target(raw)
        if not label:
            continue
        targets.append((len(targets), label, target))

    scan_prompt = (prompt or "").strip() or "Reply with exactly: OK"
    sanitized_kwargs = {k: v for k, v in (create_kwargs or {}).items() if v is not None}
    base_messages = [msg("user", scan_prompt)]

    delay = max(0.0, float(delay_seconds))
    workers = max(1, int(max_workers))
    started_at = now_iso()
    started_monotonic = time.monotonic()

    def run_single(idx: int, label: str, model_value: Any) -> Tuple[int, ModelScanResult]:
        if delay > 0:
            scheduled_start = started_monotonic + (idx * delay)
            wait = scheduled_start - time.monotonic()
            if wait > 0:
                time.sleep(wait)

        scan_start = time.perf_counter()
        try:
            response = g4f.ChatCompletion.create(
                model=model_value,
                messages=base_messages,
                provider=provider,
                **sanitized_kwargs,
            )
            text = _coerce_chat_response_text(response).strip()
            elapsed = round(time.perf_counter() - scan_start, 4)
            if not text:
                return (
                    idx,
                    ModelScanResult(
                        model=label,
                        ok=False,
                        status="no_response",
                        elapsed_seconds=elapsed,
                        error="No response content returned.",
                    ),
                )
            return (
                idx,
                ModelScanResult(
                    model=label,
                    ok=True,
                    status="ok",
                    elapsed_seconds=elapsed,
                    response_preview=clamp(text, response_preview_chars),
                ),
            )
        except Exception as e:
            elapsed = round(time.perf_counter() - scan_start, 4)
            return (
                idx,
                ModelScanResult(
                    model=label,
                    ok=False,
                    status="error",
                    elapsed_seconds=elapsed,
                    error=str(e),
                ),
            )

    indexed_results: List[Tuple[int, ModelScanResult]] = []
    use_parallel = bool(parallel and workers > 1 and len(targets) > 1)
    if use_parallel:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(run_single, idx, label, model_value): idx
                for idx, label, model_value in targets
            }
            for fut in as_completed(future_map):
                indexed_results.append(fut.result())
    else:
        for idx, label, model_value in targets:
            indexed_results.append(run_single(idx, label, model_value))

    indexed_results.sort(key=lambda item: item[0])
    results = [item[1] for item in indexed_results]
    finished_at = now_iso()
    duration = round(time.monotonic() - started_monotonic, 4)
    return ModelScanSummary(
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        prompt=scan_prompt,
        provider=provider,
        delay_seconds=delay,
        parallel=use_parallel,
        max_workers=workers,
        results=results,
    )


@dataclass
class ProjectFile:
    """Represents a tracked file in a generated project.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - ProjectFile: A configured `ProjectFile` instance.
    Example:
    ```python
    obj = ProjectFile(...)
    ```
    """

    path: str
    spec: str = ""
    content: Optional[str] = None
    accepted: bool = False
    status: str = "pending"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the project file into a plain dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        return {
            "path": self.path,
            "spec": self.spec,
            "content": self.content,
            "accepted": self.accepted,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class Project:
    """Stores accepted artifacts, model interactions, and current runtime state.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - Project: A configured `Project` instance.
    Example:
    ```python
    obj = Project(...)
    ```
    """

    name: str = "project"
    accepted_data: Dict[str, Any] = field(default_factory=dict)
    chat_history: List[Dict[str, Any]] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)
    files: List[ProjectFile] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize project state into a plain dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        return {
            "name": self.name,
            "accepted_data": deepcopy(self.accepted_data),
            "chat_history": deepcopy(self.chat_history),
            "state": deepcopy(self.state),
            "files": [f.to_dict() for f in self.files],
        }

    def set_state(self, key: str, value: Any) -> None:
        """Set a single project state key.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.set_state(...)
        ```
        """
        self.state[str(key)] = deepcopy(value)

    def update_state(self, updates: Dict[str, Any]) -> None:
        """Merge multiple keys into current project state.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.update_state(...)
        ```
        """
        if not isinstance(updates, dict):
            return
        for k, v in updates.items():
            self.state[str(k)] = deepcopy(v)

    def accept(self, key: str, value: Any) -> None:
        """Store accepted data under a top-level key.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.accept(...)
        ```
        """
        self.accepted_data[str(key)] = deepcopy(value)

    def append_accepted(self, key: str, value: Any) -> None:
        """Append a value into an accepted-data list bucket.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.append_accepted(...)
        ```
        """
        bucket_key = str(key)
        current = self.accepted_data.get(bucket_key)
        if current is None:
            current = []
            self.accepted_data[bucket_key] = current
        if not isinstance(current, list):
            raise TypeError(f"Accepted data key '{bucket_key}' is not a list")
        current.append(deepcopy(value))

    def set_accepted_entry(self, key: str, entry_key: str, value: Any) -> None:
        """Set a keyed entry in a map-style accepted-data bucket.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.set_accepted_entry(...)
        ```
        """
        bucket_key = str(key)
        current = self.accepted_data.get(bucket_key)
        if current is None:
            current = {}
            self.accepted_data[bucket_key] = current
        if not isinstance(current, dict):
            raise TypeError(f"Accepted data key '{bucket_key}' is not a dictionary")
        current[str(entry_key)] = deepcopy(value)

    def get_file(self, path: str) -> Optional[ProjectFile]:
        """Return a tracked file by path, if present.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.get_file(...)
        ```
        """
        needle = str(path)
        for f in self.files:
            if f.path == needle:
                return f
        return None

    def upsert_file(
        self,
        path: str,
        spec: Optional[str] = None,
        content: Optional[str] = None,
        accepted: Optional[bool] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ProjectFile:
        """Create/update a tracked project file and return it.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.upsert_file(...)
        ```
        """
        normalized = str(path)
        f = self.get_file(normalized)
        if f is None:
            f = ProjectFile(path=normalized)
            self.files.append(f)
        if spec is not None:
            f.spec = str(spec)
        if content is not None:
            f.content = content
        if accepted is not None:
            f.accepted = bool(accepted)
        if status is not None:
            f.status = str(status)
        if notes is not None:
            f.notes = str(notes)
        return f

    def record_chat(
        self,
        *,
        stage_name: Optional[str],
        role_name: Optional[str],
        model: str,
        provider: Optional[str],
        messages: Messages,
        create_kwargs: Optional[Dict[str, Any]],
        response: Optional[str],
        error: Optional[str] = None,
        attempt: Optional[int] = None,
    ) -> None:
        """Append a model interaction to chat history.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.record_chat(...)
        ```
        """
        entry: Dict[str, Any] = {
            "timestamp": now_iso(),
            "stage": stage_name,
            "role": role_name,
            "model": model,
            "provider": provider,
            "messages": deepcopy(list(messages)),
            "create_kwargs": deepcopy(create_kwargs or {}),
            "response": response,
        }
        if error is not None:
            entry["error"] = str(error)
        if attempt is not None:
            entry["attempt"] = int(attempt)
        self.chat_history.append(entry)


@dataclass
class Agent:
    """Represents a single role definition and request-building behavior.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - Agent: A configured `Agent` instance.
    Example:
    ```python
    obj = Agent(...)
    ```
    """

    role: str
    prompt: str
    user_prompt_template: str
    model: Optional[str] = None
    provider: Optional[str] = None
    description: str = ""
    g4f_params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_definition(cls, role: str, definition: Dict[str, Any]) -> "Agent":
        """Create an agent from a role name and JSON-like definition object.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.from_definition(...)
        ```
        """
        return cls(
            role=role,
            prompt=str(definition.get("prompt", "")),
            user_prompt_template=str(definition.get("user_prompt_template", "")),
            model=definition.get("model"),
            provider=definition.get("provider"),
            description=str(definition.get("description", "")),
            g4f_params=dict(definition.get("g4f_params", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the agent into a plain dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        return {
            "role": self.role,
            "prompt": self.prompt,
            "user_prompt_template": self.user_prompt_template,
            "model": self.model,
            "provider": self.provider,
            "description": self.description,
            "g4f_params": dict(self.g4f_params),
        }

    def clone_with(self, **updates: Any) -> "Agent":
        """Return a copy of this agent with selected fields updated.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.clone_with(...)
        ```
        """
        data = self.to_dict()
        data.update(updates)
        return Agent(**data)

    def build_messages(self, template_context: Dict[str, Any]) -> Messages:
        """Build system/user messages using the agent templates.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.build_messages(...)
        ```
        """
        return [
            msg("system", self.prompt),
            msg("user", format_template(self.user_prompt_template, template_context)),
        ]

    def build_request(
        self,
        defaults: Dict[str, Any],
        stage_overrides: Dict[str, Any],
        cli_model: Optional[str],
        cli_temperature: Optional[float],
        fallback_retries: int,
    ) -> Tuple[str, Optional[str], Dict[str, Any], int]:
        """Build model/provider/kwargs/retry tuple for a chat request.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.build_request(...)
        ```
        """
        merged_params = deep_merge_dict(defaults, self.g4f_params)
        merged_params = deep_merge_dict(merged_params, (stage_overrides.get("g4f_params", {}) or {}))
        if cli_temperature is not None:
            merged_params["temperature"] = cli_temperature

        max_retries = int(merged_params.pop("max_retries", fallback_retries))
        extra_kwargs = merged_params.pop("extra_kwargs", {}) or {}

        model_name = cli_model or stage_overrides.get("model") or self.model
        provider_name = stage_overrides.get("provider", self.provider)
        resolved_model = resolve_model_name(model_name)

        create_kwargs: Dict[str, Any] = {}
        for k, v in merged_params.items():
            if k in G4F_SUPPORTED_CHAT_PARAMS and v is not None:
                create_kwargs[k] = v
        if isinstance(extra_kwargs, dict):
            for k, v in extra_kwargs.items():
                if v is not None:
                    create_kwargs[k] = v
        if "response_format" in create_kwargs:
            create_kwargs["response_format"] = enforce_strict_json_object_response_format(
                create_kwargs["response_format"]
            )
        return resolved_model, provider_name, create_kwargs, max_retries


@dataclass
class Stage:
    """Represents a pipeline stage and the agents assigned to it.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - Stage: A configured `Stage` instance.
    Example:
    ```python
    obj = Stage(...)
    ```
    """

    name: str
    agents: List[Agent] = field(default_factory=list)
    overrides: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls,
        name: str,
        stage_config: Dict[str, Any],
        agent_lookup: Dict[str, Agent],
    ) -> "Stage":
        """Construct a stage from pipeline config and known agents.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.from_config(...)
        ```
        """
        role = stage_config.get("role")
        roles = stage_config.get("roles")
        if isinstance(roles, list) and roles:
            role_names = [str(r) for r in roles]
        else:
            role_names = [str(role)] if role else []

        agents: List[Agent] = []
        for role_name in role_names:
            agent = agent_lookup.get(role_name)
            if agent is None:
                raise KeyError(f"Stage '{name}' references unknown role '{role_name}'")
            agents.append(agent)

        if not agents:
            raise ValueError(f"Stage '{name}' must define at least one role/agent")

        return cls(name=name, agents=agents, overrides=dict(stage_config.get("overrides", {}) or {}))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the stage into a plain dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        return {
            "name": self.name,
            "roles": [a.role for a in self.agents],
            "overrides": dict(self.overrides),
        }

    def list_agent_roles(self) -> List[str]:
        """Return all role names assigned to this stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.list_agent_roles(...)
        ```
        """
        return [agent.role for agent in self.agents]

    def has_agent(self, role: str) -> bool:
        """Return whether a role is assigned to this stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.has_agent(...)
        ```
        """
        return any(agent.role == role for agent in self.agents)

    def get_agent(self, role: str) -> Agent:
        """Return the stage agent for a specific role.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.get_agent(...)
        ```
        """
        for agent in self.agents:
            if agent.role == role:
                return agent
        raise KeyError(f"Stage '{self.name}' does not include role '{role}'")

    def add_agent(self, agent: Agent) -> None:
        """Attach an agent to this stage if not already present.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.add_agent(...)
        ```
        """
        if self.has_agent(agent.role):
            return
        self.agents.append(agent)

    def primary_agent(self) -> Agent:
        """Return the primary agent used for stage execution.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.primary_agent(...)
        ```
        """
        if not self.agents:
            raise ValueError(f"Stage '{self.name}' has no agents")
        return self.agents[0]

    def role_name(self) -> str:
        """Return the primary role name for this stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.role_name(...)
        ```
        """
        return self.primary_agent().role

    def provider_label(self) -> Optional[str]:
        """Return the effective provider label for this stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.provider_label(...)
        ```
        """
        agent = self.primary_agent()
        return self.overrides.get("provider", agent.provider)

    def model_label(self, cli_model: Optional[str]) -> str:
        """Return the effective model label for this stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.model_label(...)
        ```
        """
        agent = self.primary_agent()
        return resolve_model_name(cli_model or self.overrides.get("model") or agent.model)

    def build_messages(self, template_context: Dict[str, Any]) -> Messages:
        """Build stage messages using the primary agent.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.build_messages(...)
        ```
        """
        return self.primary_agent().build_messages(template_context)

    def build_request(
        self,
        defaults: Dict[str, Any],
        cli_model: Optional[str],
        cli_temperature: Optional[float],
        fallback_retries: int,
    ) -> Tuple[str, Optional[str], Dict[str, Any], int]:
        """Build request parameters for the stage's primary agent.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.build_request(...)
        ```
        """
        return self.primary_agent().build_request(
            defaults=defaults,
            stage_overrides=self.overrides,
            cli_model=cli_model,
            cli_temperature=cli_temperature,
            fallback_retries=fallback_retries,
        )


@dataclass
class Pipeline:
    """Represents an ordered collection of execution stages.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - Pipeline: A configured `Pipeline` instance.
    Example:
    ```python
    obj = Pipeline(...)
    ```
    """

    stages: List[Stage] = field(default_factory=list)
    order: List[str] = field(default_factory=list)

    @classmethod
    def from_runtime_config(
        cls,
        runtime_cfg: Dict[str, Any],
        agent_lookup: Dict[str, Agent],
    ) -> "Pipeline":
        """Construct a pipeline from runtime config and agent lookup.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.from_runtime_config(...)
        ```
        """
        pipeline_cfg = (runtime_cfg.get("pipeline", {}) or {})
        stages_cfg = (pipeline_cfg.get("stages", {}) or {})
        configured_order = pipeline_cfg.get("order", [])
        if isinstance(configured_order, list):
            order = [str(s) for s in configured_order if isinstance(s, str) and s]
        else:
            order = []

        if not order:
            order = [str(name) for name in stages_cfg.keys()]

        stages: List[Stage] = []
        for stage_name in order:
            stage_cfg = stages_cfg.get(stage_name)
            if not isinstance(stage_cfg, dict):
                raise KeyError(f"Missing stage config for '{stage_name}'")
            stages.append(Stage.from_config(stage_name, stage_cfg, agent_lookup))

        return cls(stages=stages, order=order)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the pipeline into a plain dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        return {
            "order": list(self.order),
            "stages": [stage.to_dict() for stage in self.stages],
        }

    def list_stage_names(self) -> List[str]:
        """Return stage names in execution order.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.list_stage_names(...)
        ```
        """
        return [stage.name for stage in self.stages]

    def has_stage(self, stage_name: str) -> bool:
        """Return whether a stage exists in this pipeline.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.has_stage(...)
        ```
        """
        return any(stage.name == stage_name for stage in self.stages)

    def get_stage(self, stage_name: str) -> Stage:
        """Return a stage by name.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.get_stage(...)
        ```
        """
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        raise KeyError(f"Unknown stage: {stage_name}")

    def add_stage(self, stage: Stage) -> None:
        """Append a new stage to the pipeline if not already present.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.add_stage(...)
        ```
        """
        if self.has_stage(stage.name):
            return
        self.stages.append(stage)
        self.order.append(stage.name)


class G4FManager:
    """Primary SDK interface for agent/pipeline-aware g4f interactions.
    
    Inputs:
    - Constructor fields and initialization parameters defined for this class.
    Output:
    - G4FManager: A configured `G4FManager` instance.
    Example:
    ```python
    obj = G4FManager(...)
    ```
    """

    def __init__(
        self,
        runtime_cfg: Dict[str, Any],
        cfg: Optional[LLMConfig] = None,
        project: Optional[Project] = None,
    ):
        """Initialize the manager from resolved runtime configuration.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        value = instance.__init__(...)
        ```
        """
        self.runtime_cfg = runtime_cfg
        default_retries = int((runtime_cfg.get("g4f_defaults", {}) or {}).get("max_retries", 2))
        self.cfg = cfg or LLMConfig(max_retries=default_retries)
        self.project = project or Project()

        loaded_agents = (runtime_cfg.get("loaded_agents", {}) or {})
        self.agents: List[Agent] = [
            Agent.from_definition(str(role), definition)
            for role, definition in loaded_agents.items()
            if isinstance(definition, dict)
        ]
        self._agents_by_role: Dict[str, Agent] = {agent.role: agent for agent in self.agents}
        self.pipeline = Pipeline.from_runtime_config(runtime_cfg, self._agents_by_role)

    @classmethod
    def from_runtime_config(
        cls,
        runtime_cfg: Dict[str, Any],
        cfg: Optional[LLMConfig] = None,
        project: Optional[Project] = None,
    ) -> "G4FManager":
        """Create a manager from an in-memory runtime config object.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.from_runtime_config(...)
        ```
        """
        return cls(runtime_cfg=runtime_cfg, cfg=cfg, project=project)

    @classmethod
    def from_config(
        cls,
        config_rel_path: str = DEFAULT_CONFIG_REL_PATH,
        base_dir: Path = APP_ROOT,
        cfg: Optional[LLMConfig] = None,
        project: Optional[Project] = None,
    ) -> "G4FManager":
        """Load configuration from disk and build a manager instance.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.from_config(...)
        ```
        """
        runtime_cfg = load_runtime_config(base_dir, config_rel_path)
        return cls(runtime_cfg=runtime_cfg, cfg=cfg, project=project)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manager state to a dictionary.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.to_dict(...)
        ```
        """
        return {
            "agents": [agent.to_dict() for agent in self.agents],
            "pipeline": self.pipeline.to_dict(),
            "meta": dict((self.runtime_cfg.get("_meta", {}) or {})),
            "project": self.project.to_dict(),
        }

    def get_project(self) -> Project:
        """Return the mutable project state container.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.get_project(...)
        ```
        """
        return self.project

    def get_runtime_config(self) -> Dict[str, Any]:
        """Return the runtime configuration backing this manager.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.get_runtime_config(...)
        ```
        """
        return self.runtime_cfg

    def metadata(self) -> Dict[str, Any]:
        """Return config metadata such as resolved config and agent paths.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.metadata(...)
        ```
        """
        return dict((self.runtime_cfg.get("_meta", {}) or {}))

    def list_agents(self) -> List[str]:
        """Return role names for all registered agents.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.list_agents(...)
        ```
        """
        return [agent.role for agent in self.agents]

    def get_agent(self, role: str) -> Agent:
        """Return an agent by role name.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.get_agent(...)
        ```
        """
        agent = self._agents_by_role.get(role)
        if agent is None:
            raise KeyError(f"Unknown agent role: {role}")
        return agent

    def list_stages(self) -> List[str]:
        """Return pipeline stage names in execution order.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.list_stages(...)
        ```
        """
        return self.pipeline.list_stage_names()

    def get_stage(self, stage_name: str) -> Stage:
        """Return a stage from the pipeline by name.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.get_stage(...)
        ```
        """
        return self.pipeline.get_stage(stage_name)

    def default_stage_names(self) -> Tuple[str, str]:
        """Return default planning and writing stage names.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.default_stage_names(...)
        ```
        """
        return resolve_pipeline_stages(self.runtime_cfg)

    def stage_role_name(self, stage_name: str) -> str:
        """Return the primary role name used by a stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.stage_role_name(...)
        ```
        """
        return self.get_stage(stage_name).role_name()

    def stage_model_label(self, stage_name: str, cli_model: Optional[str]) -> str:
        """Return the effective model label for a stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.stage_model_label(...)
        ```
        """
        return self.get_stage(stage_name).model_label(cli_model)

    def stage_provider_label(self, stage_name: str) -> Optional[str]:
        """Return the effective provider label for a stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.stage_provider_label(...)
        ```
        """
        return self.get_stage(stage_name).provider_label()

    def build_stage_messages(self, stage_name: str, template_context: Dict[str, Any]) -> Messages:
        """Build templated messages for a stage.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.build_stage_messages(...)
        ```
        """
        return self.get_stage(stage_name).build_messages(template_context)

    def build_stage_request(
        self,
        stage_name: str,
        cli_model: Optional[str],
        cli_temperature: Optional[float],
    ) -> Tuple[str, Optional[str], Dict[str, Any], int]:
        """Build request parameters for a stage execution.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.build_stage_request(...)
        ```
        """
        return self.get_stage(stage_name).build_request(
            defaults=(self.runtime_cfg.get("g4f_defaults", {}) or {}),
            cli_model=cli_model,
            cli_temperature=cli_temperature,
            fallback_retries=self.cfg.max_retries,
        )

    def scan_models(
        self,
        models: Optional[List[Any]] = None,
        *,
        provider: Optional[str] = None,
        prompt: str = "Reply with exactly: OK",
        create_kwargs: Optional[Dict[str, Any]] = None,
        delay_seconds: float = 0.0,
        parallel: bool = False,
        max_workers: int = 4,
        response_preview_chars: int = 180,
    ) -> ModelScanSummary:
        """Run model availability probing using runtime defaults plus overrides.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.scan_models(...)
        ```
        """
        defaults = (self.runtime_cfg.get("g4f_defaults", {}) or {})
        scan_excluded_keys = {
            "max_retries",
            "response_format",
            "stream",
            "tool_calls",
            "tools",
            "parallel_tool_calls",
            "tool_choice",
            "conversation_id",
            "conversation",
            "image",
            "image_name",
            "images",
            "media",
            "audio",
            "modalities",
            "download_media",
        }
        merged_kwargs: Dict[str, Any] = {}
        for k, v in defaults.items():
            if k in scan_excluded_keys:
                continue
            if k not in G4F_SUPPORTED_CHAT_PARAMS:
                continue
            if v is None:
                continue
            merged_kwargs[k] = v
        for k, v in (create_kwargs or {}).items():
            if v is None:
                continue
            merged_kwargs[k] = v

        return scan_models(
            models=models,
            provider=provider,
            prompt=prompt,
            create_kwargs=merged_kwargs,
            delay_seconds=delay_seconds,
            parallel=parallel,
            max_workers=max_workers,
            response_preview_chars=response_preview_chars,
        )

    def detect_verification_program_paths(
        self,
        programs: Optional[List[str]] = None,
        *,
        max_matches_per_program: int = 5,
    ) -> Dict[str, Any]:
        """Detect common verifier/debug-cycle executables and command suggestions.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.detect_verification_program_paths(...)
        ```
        """
        return detect_verification_program_paths_util(
            programs=programs,
            max_matches_per_program=max_matches_per_program,
        )

    def chat(
        self,
        messages: Messages,
        model: str,
        provider: Optional[str] = None,
        create_kwargs: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        stage_name: Optional[str] = None,
        image: Any = None,
        image_name: Optional[str] = None,
        images: Any = None,
        media: Any = None,
    ) -> str:
        """Execute a raw chat completion call through g4f.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.chat(...)
        ```
        """
        create_kwargs = merge_prompt_media_kwargs(
            create_kwargs,
            image=image,
            image_name=image_name,
            images=images,
            media=media,
        )
        retries = max_retries if max_retries is not None else self.cfg.max_retries
        last_err = None
        role_name: Optional[str] = None
        if stage_name:
            try:
                role_name = self.get_stage(stage_name).role_name()
            except Exception:
                role_name = None
        if self.cfg.log_requests:
            print(f"Calling G4F model: {model} (provider={provider or 'auto'}, max_retries={retries})")
            print(f"Messages (truncated):\n{clamp(pretty_json(messages), 2000)}")

        for attempt in range(1, retries + 2):
            try:
                resp = g4f.ChatCompletion.create(
                    model=model,
                    messages=messages,
                    provider=provider,
                    **create_kwargs,
                )
                text_response = _coerce_chat_response_text(resp)
                self.project.record_chat(
                    stage_name=stage_name,
                    role_name=role_name,
                    model=model,
                    provider=provider,
                    messages=messages,
                    create_kwargs=create_kwargs,
                    response=text_response,
                    attempt=attempt,
                )
                return text_response
            except Exception as e:
                last_err = e
                self.project.record_chat(
                    stage_name=stage_name,
                    role_name=role_name,
                    model=model,
                    provider=provider,
                    messages=messages,
                    create_kwargs=create_kwargs,
                    response=None,
                    error=str(e),
                    attempt=attempt,
                )
                if attempt <= retries + 1:
                    continue
        raise RuntimeError(f"G4F call failed: {last_err}")

    def chat_stage(
        self,
        stage_name: str,
        template_context: Dict[str, Any],
        cli_model: Optional[str] = None,
        cli_temperature: Optional[float] = None,
        image: Any = None,
        image_name: Optional[str] = None,
        images: Any = None,
        media: Any = None,
    ) -> str:
        """Execute a stage by building messages/request settings and chatting.
        
        Inputs:
        - Method parameters defined in the function signature (excluding `self`).
        Output:
        - The method return value as defined by its signature/annotations.
        Example:
        ```python
        result = instance.chat_stage(...)
        ```
        """
        self.project.update_state({"current_stage": stage_name})
        messages = self.build_stage_messages(stage_name, template_context)
        model, provider, create_kwargs, max_retries = self.build_stage_request(
            stage_name=stage_name,
            cli_model=cli_model,
            cli_temperature=cli_temperature,
        )
        response = self.chat(
            messages=messages,
            model=model,
            provider=provider,
            create_kwargs=create_kwargs,
            max_retries=max_retries,
            stage_name=stage_name,
            image=image,
            image_name=image_name,
            images=images,
            media=media,
        )
        self.project.update_state({"last_completed_stage": stage_name})
        return response
