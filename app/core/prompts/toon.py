from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config.settings import PROJECT_ROOT

_TOKEN_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")
_DEFAULT_CATALOG_PATH = PROJECT_ROOT / "prompts" / "prompt_catalog.toon"


def _parse_toon_value(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _parse_toon_catalog(text: str) -> dict[str, Any]:
    """Parse a minimal TOON/YAML-like prompt catalog.

    Supported subset:
    - top-level scalar keys (e.g., toon_version)
    - `prompts[N]:` list with `- id:` entries
    - prompt-level scalar fields (id, owner, why, template)
    """
    data: dict[str, Any] = {"toon_version": "1.0", "prompts": []}
    prompts: list[dict[str, Any]] = []
    current_prompt: dict[str, Any] | None = None
    current_nested_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        stripped = line.strip()

        if stripped.startswith("prompts[") and stripped.endswith(":"):
            continue

        if stripped.startswith("- "):
            payload = stripped[2:]
            if ":" not in payload:
                continue
            key, value = payload.split(":", 1)
            current_prompt = {key.strip(): _parse_toon_value(value)}
            prompts.append(current_prompt)
            current_nested_key = None
            continue

        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        parsed_value = _parse_toon_value(value)

        if current_prompt is not None and line.startswith("      ") and current_nested_key:
            nested_value = current_prompt.get(current_nested_key)
            if not isinstance(nested_value, dict):
                nested_value = {}
                current_prompt[current_nested_key] = nested_value
            nested_value[key] = parsed_value
        elif current_prompt is not None and line.startswith("    "):
            current_prompt[key] = parsed_value
            current_nested_key = key if value.strip() == "" else None
        elif line.startswith("  "):
            # Ignore nested non-prompt objects (optimization_scope etc.) for now.
            continue
        else:
            data[key] = parsed_value
            current_prompt = None
            current_nested_key = None

    data["prompts"] = prompts
    return data


@lru_cache
def load_prompt_catalog(path: str | None = None) -> dict[str, Any]:
    catalog_path = Path(path) if path else _DEFAULT_CATALOG_PATH
    if not catalog_path.exists():
        return {"toon_version": "1.0", "prompts": []}

    try:
        raw_text = catalog_path.read_text(encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        return {"toon_version": "1.0", "prompts": []}

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        data = _parse_toon_catalog(raw_text)

    if not isinstance(data, dict):
        return {"toon_version": "1.0", "prompts": []}

    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        prompts = []
    data["prompts"] = prompts
    return data


def get_prompt_spec(prompt_id: str, path: str | None = None) -> dict[str, Any] | None:
    prompts = load_prompt_catalog(path=path).get("prompts", [])
    for item in prompts:
        if isinstance(item, dict) and str(item.get("id", "")).strip() == prompt_id:
            return item
    return None


def _estimate_tokens(text: str) -> int:
    # Rough estimate for LLM budgeting: ~4 chars/token in English-like text.
    return max(1, int((len(text) + 3) / 4)) if text else 0


def render_prompt(prompt_id: str, values: dict[str, Any] | None = None, path: str | None = None) -> str:
    values = values or {}
    spec = get_prompt_spec(prompt_id, path=path)
    if not spec:
        return ""

    template = str(spec.get("template", ""))
    placeholder_keys = sorted(set(_TOKEN_PATTERN.findall(template)))

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        return "" if value is None else str(value)

    rendered = _TOKEN_PATTERN.sub(_replace, template)

    # Emit observability event if enabled
    try:
        from app.core.observability.langsmith import emit_local_observability_event

        emit_local_observability_event(
            "prompt_render",
            {
                "prompt_id": prompt_id,
                "owner": str(spec.get("owner", "")).strip(),
                "rendered_chars": len(rendered),
                "estimated_tokens": _estimate_tokens(rendered),
                "placeholders": placeholder_keys,
                "provided_values": sorted(values.keys()),
            },
        )
    except Exception:
        # Silently skip observability on import/emit failure
        pass

    return rendered


def prompt_catalog_summary(path: str | None = None) -> dict[str, Any]:
    data = load_prompt_catalog(path=path)
    prompts = data.get("prompts", [])
    summary: list[dict[str, Any]] = []
    for item in prompts:
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "id": str(item.get("id", "")).strip(),
                "owner": str(item.get("owner", "")).strip(),
                "why": str(item.get("why", "")).strip(),
                "optimization_scope": item.get("optimization_scope", {}),
            }
        )
    return {
        "toon_version": str(data.get("toon_version", "1.0")),
        "prompt_count": len(summary),
        "prompts": summary,
    }


def prompt_usage_summary(limit: int = 2000, path: str | None = None) -> dict[str, Any]:
    from app.core.observability.langsmith import get_local_trace_events

    data = load_prompt_catalog(path=path)
    prompts = [item for item in data.get("prompts", []) if isinstance(item, dict)]
    prompt_specs = {
        str(item.get("id", "")).strip(): item
        for item in prompts
        if str(item.get("id", "")).strip()
    }

    events = get_local_trace_events(limit=limit)
    prompt_events = [
        event for event in events if isinstance(event, dict) and event.get("event") == "prompt_render"
    ]

    aggregates: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "prompt_id": "",
            "renders": 0,
            "estimated_tokens_total": 0,
            "rendered_chars_total": 0,
            "avg_rendered_chars": 0,
            "last_seen": "",
        }
    )

    for event in prompt_events:
        prompt_id = str(event.get("prompt_id", "")).strip()
        if not prompt_id:
            continue

        item = aggregates[prompt_id]
        item["prompt_id"] = prompt_id
        item["renders"] += 1
        item["estimated_tokens_total"] += int(event.get("estimated_tokens") or 0)
        item["rendered_chars_total"] += int(event.get("rendered_chars") or 0)

        timestamp = str(event.get("timestamp", "")).strip()
        if timestamp:
            previous = item.get("last_seen") or ""
            item["last_seen"] = max(previous, timestamp) if previous else timestamp

    results: list[dict[str, Any]] = []
    for prompt_id, item in aggregates.items():
        renders = max(int(item.get("renders", 0)), 1)
        item["avg_rendered_chars"] = round(float(item.get("rendered_chars_total", 0)) / renders, 2)

        spec = prompt_specs.get(prompt_id, {})
        optimization_scope = spec.get("optimization_scope", {}) if isinstance(spec, dict) else {}
        item["owner"] = str(spec.get("owner", "")).strip() if isinstance(spec, dict) else ""
        item["why"] = str(spec.get("why", "")).strip() if isinstance(spec, dict) else ""
        item["optimization_scope"] = optimization_scope if isinstance(optimization_scope, dict) else {}
        results.append(item)

    results.sort(key=lambda entry: (-int(entry.get("renders", 0)), entry.get("prompt_id", "")))

    return {
        "toon_version": str(data.get("toon_version", "1.0")),
        "catalog_prompt_count": len(prompt_specs),
        "render_events_analyzed": len(prompt_events),
        "unique_prompts_rendered": len(results),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "prompts": results,
    }
    prompts = data.get("prompts", [])
    summary: list[dict[str, Any]] = []
    for item in prompts:
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "id": str(item.get("id", "")).strip(),
                "owner": str(item.get("owner", "")).strip(),
                "why": str(item.get("why", "")).strip(),
                "optimization_scope": item.get("optimization_scope", {}),
            }
        )
    return {
        "toon_version": str(data.get("toon_version", "1.0")),
        "prompt_count": len(summary),
        "prompts": summary,
    }
