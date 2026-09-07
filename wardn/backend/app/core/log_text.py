"""Readable console summaries, adapted from DevFeed's shared logging system."""

import json
import re
from datetime import datetime


def inline(value) -> str:
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
    return encoded[1:-1] if isinstance(value, str) else encoded


def short_id(value) -> str:
    value = str(value)
    return value[:8] if re.fullmatch(r"[0-9a-f-]{32,64}", value) else inline(value)[:40]


def local_time(value: str) -> str:
    return datetime.fromisoformat(value).astimezone().strftime("%H:%M:%S")


def event_text(payload: dict) -> str:
    event = payload["event"]
    if event == "request_completed":
        return (
            f"{inline(payload.get('method', 'HTTP'))} "
            f"{inline(payload.get('request_url', payload.get('route', '<unmatched>')))} "
            f"-> {payload.get('status_code', '?')}"
        )
    if event in {"dependency_log", "application_log"}:
        return f"{inline(payload['logger'])}: {payload['level'].lower()} (message omitted)"
    message = payload.get("message", event.replace("_", " ").capitalize())
    if "mcp_job_progress_current" in payload and "mcp_job_progress_total" in payload:
        return (
            "MCP operation job progress: "
            f"{payload['mcp_job_progress_current']}/{payload['mcp_job_progress_total']}"
        )
    if payload.get("mcp_catalog_synced_count") is not None:
        message += f" {payload['mcp_catalog_synced_count']} server versions synced"
    return message


def error_text(payload: dict, *, verbose: bool) -> str:
    exceptions = payload.get("exception", [])
    if not exceptions:
        return inline(payload["error_type"]) if payload.get("error_type") else ""
    parts = []
    for index, detail in enumerate(exceptions):
        description = inline(detail["type"])
        if detail.get("missing_name"):
            description += f": {inline(detail['missing_name'])} is not defined"
        if detail.get("attribute"):
            owner = detail.get("object_type", "object")
            description += f": {inline(owner)}.{inline(detail['attribute'])} is missing"
        frames = detail["frames"] if verbose else detail["frames"][-1:]
        if frames:
            locations = [
                f"{inline(frame['file'])}:{frame['line']}"
                + (f" in {inline(frame['function'])}" if verbose else "")
                for frame in frames
            ]
            description += " at " + " -> ".join(locations)
        parts.append(("caused by " if index else "") + description)
    return "; ".join(parts)


def context_text(payload: dict, *, verbose: bool) -> list[str]:
    if verbose:
        return [
            f"{key}={inline(value)}"
            for key, value in payload.items()
            if key not in {"timestamp", "level", "service", "exception", "message"}
            and value is not None
        ]
    parts = []
    for keys, label in [
        (("mcp_job_id", "job_id", "scheduled_task_run_id", "agent_run_resume_job_id"), "job"),
        (("agent_run_id",), "run"),
        (("mcp_catalog_source_id",), "source"),
        (("mcp_installation_id", "installation_id"), "installation"),
    ]:
        value = next((payload[key] for key in keys if payload.get(key)), None)
        if value:
            parts.append(f"{label} {short_id(value)}")
            break
    if payload.get("attempt"):
        parts.append(f"attempt {payload['attempt']}")
    duration = payload.get("duration_ms")
    if isinstance(duration, (int, float)):
        parts.append(f"{duration:.0f} ms" if duration < 1000 else f"{duration / 1000:.2f} s")
    if payload.get("request_id") and payload["level"] in {"WARNING", "ERROR", "CRITICAL"}:
        parts.append(f"request {short_id(payload['request_id'])}")
    return parts
