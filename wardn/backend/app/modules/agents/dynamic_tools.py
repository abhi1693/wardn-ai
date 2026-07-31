import json
import re
from typing import Any

from app.modules.agents.tool_execution import tool_execution_result
from app.modules.agents.types import (
    FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
    FAILURE_TOOL_INSTALLED_NOT_ASSIGNED,
    FAILURE_TOOL_NOT_INSTALLED,
    AgentInstalledTool,
    AgentRuntimeTool,
    AgentRuntimeToolGuardrailFilter,
    AgentToolCall,
    AgentToolExecutionResult,
)

AGENT_SEARCH_TOOLS_TOOL_NAME = "search_tools"
AGENT_RUN_TOOL_TOOL_NAME = "run_tool"
AGENT_DYNAMIC_TOOL_NAMES = {
    AGENT_SEARCH_TOOLS_TOOL_NAME,
    AGENT_RUN_TOOL_TOOL_NAME,
}
AGENT_SEARCH_TOOLS_DEFAULT_LIMIT = 8
AGENT_SEARCH_TOOLS_MAX_LIMIT = 20
SEARCH_STOP_WORDS = {
    "a",
    "all",
    "an",
    "and",
    "call",
    "check",
    "create",
    "delete",
    "do",
    "fetch",
    "find",
    "for",
    "from",
    "get",
    "give",
    "in",
    "into",
    "latest",
    "list",
    "me",
    "my",
    "of",
    "on",
    "please",
    "read",
    "run",
    "search",
    "show",
    "the",
    "to",
    "update",
    "use",
    "using",
    "with",
}


AgentToolCatalog = AgentRuntimeToolGuardrailFilter | dict[str, AgentRuntimeTool]


def allowed_catalog_tools(catalog: AgentToolCatalog) -> dict[str, AgentRuntimeTool]:
    if isinstance(catalog, AgentRuntimeToolGuardrailFilter):
        return catalog.allowed_tools
    return catalog


def denied_catalog_tools(
    catalog: AgentToolCatalog,
) -> dict[str, tuple[AgentRuntimeTool, Any]]:
    if isinstance(catalog, AgentRuntimeToolGuardrailFilter):
        return catalog.denied_tools
    return {}


def installed_catalog_tools(catalog: AgentToolCatalog) -> dict[str, AgentInstalledTool]:
    if isinstance(catalog, AgentRuntimeToolGuardrailFilter):
        return catalog.installed_tools or {}
    return {}


def agent_dynamic_function_tools(catalog: AgentToolCatalog) -> list[dict[str, Any]]:
    assigned_tool_count = len(allowed_catalog_tools(catalog)) + len(denied_catalog_tools(catalog))
    if assigned_tool_count == 0 and not installed_catalog_tools(catalog):
        return []
    return [
        {
            "type": "function",
            "name": AGENT_SEARCH_TOOLS_TOOL_NAME,
            "description": (
                "Diagnose MCP tool capability for this agent. Searches installed workspace "
                "tools and reports whether each match is executable, installed but not "
                "assigned, or assigned but blocked by policy. Only returned tools with "
                "capabilityStatus=allowed have exact toolName values that can be passed to "
                f"{AGENT_RUN_TOOL_TOOL_NAME}. Search by capability and system name, not only "
                "by the object being inspected; for example 'google search console gsc "
                "shipyardhq.dev', 'kubernetes namespaces rancher-qa', or 'arxiv papers'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keywords for the capability and target, for example "
                            "'google search console gsc', 'kubernetes namespaces "
                            "rancher-qa', or 'arxiv read paper'."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": AGENT_SEARCH_TOOLS_MAX_LIMIT,
                        "default": AGENT_SEARCH_TOOLS_DEFAULT_LIMIT,
                        "description": "Maximum number of matching tools to return.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": AGENT_RUN_TOOL_TOOL_NAME,
            "description": (
                "Execute one MCP tool available to this agent. Use the exact toolName returned "
                f"by {AGENT_SEARCH_TOOLS_TOOL_NAME}; put the target tool arguments in tool_args. "
                "Do not copy configuredTarget into tool_args; Wardn uses configuredTarget to "
                "route to the configured MCP installation. "
                "The target tool is resolved server-side and evaluated by guardrail policies "
                "again immediately before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": (
                            f"Exact toolName returned by {AGENT_SEARCH_TOOLS_TOOL_NAME}."
                        ),
                    },
                    "tool_args": {
                        "type": "object",
                        "description": "Arguments for the target MCP tool.",
                        "additionalProperties": True,
                    },
                },
                "required": ["tool_name"],
                "additionalProperties": False,
            },
        },
    ]


def is_agent_dynamic_tool_name(name: str) -> bool:
    return name in AGENT_DYNAMIC_TOOL_NAMES


def execute_agent_search_tools(
    catalog: AgentToolCatalog,
    tool_call: AgentToolCall,
) -> AgentToolExecutionResult:
    query = string_arg(tool_call.arguments, "query").strip()
    if not query:
        return tool_execution_result(
            AGENT_SEARCH_TOOLS_TOOL_NAME,
            f"Tool {AGENT_SEARCH_TOOLS_TOOL_NAME} failed: query is required.",
            failure_reason=FAILURE_TOOL_NOT_INSTALLED,
        )
    limit = bounded_limit(tool_call.arguments.get("limit"))
    tools = allowed_catalog_tools(catalog)
    denied_tools = {
        wire_name: tool
        for wire_name, (tool, _decision) in denied_catalog_tools(catalog).items()
    }
    assigned_schema_ids = {
        tool.tool_schema.id for tool in list(tools.values()) + list(denied_tools.values())
    }
    unassigned_tools = {
        key: tool
        for key, tool in installed_catalog_tools(catalog).items()
        if tool.tool_schema.id not in assigned_schema_ids
    }
    matches = search_agent_tools(tools, query=query, limit=limit)
    blocked_matches = search_agent_tools(denied_tools, query=query, limit=limit)
    unassigned_matches = search_installed_tools(unassigned_tools, query=query, limit=limit)
    output = {
        "query": query,
        "totalInstalled": len(installed_catalog_tools(catalog)) or len(assigned_schema_ids),
        "totalAssigned": len(assigned_schema_ids),
        "totalAllowed": len(tools),
        "totalBlockedByPolicy": len(denied_tools),
        "matchCount": len(matches) + len(blocked_matches) + len(unassigned_matches),
        "tools": [
            tool_search_result(tool, capability_status="allowed") for tool in matches
        ],
        "blockedTools": [
            tool_search_result(
                tool,
                capability_status="assigned_blocked_policy",
                decision=denied_catalog_tools(catalog).get(tool.wire_name, (None, None))[1],
            )
            for tool in blocked_matches
        ],
        "unassignedTools": [
            installed_tool_search_result(tool) for tool in unassigned_matches
        ],
        "hint": search_hint(
            tools,
            denied_tools=denied_tools,
            unassigned_tools=unassigned_tools,
            query=query,
            matches=matches,
            blocked_matches=blocked_matches,
            unassigned_matches=unassigned_matches,
        ),
    }
    return tool_execution_result(
        AGENT_SEARCH_TOOLS_TOOL_NAME,
        json.dumps(output, indent=2, sort_keys=True, default=str),
        details={
            "query": query,
            "matchCount": output["matchCount"],
            "totalInstalled": output["totalInstalled"],
            "totalAssigned": output["totalAssigned"],
            "totalAllowed": output["totalAllowed"],
            "totalBlockedByPolicy": output["totalBlockedByPolicy"],
        },
    )


def resolve_agent_run_tool_call(
    catalog: AgentToolCatalog,
    tool_call: AgentToolCall,
) -> tuple[AgentRuntimeTool, AgentToolCall] | AgentToolExecutionResult:
    tools = allowed_catalog_tools(catalog)
    denied = denied_catalog_tools(catalog)
    denied_tools = {wire_name: tool for wire_name, (tool, _decision) in denied.items()}
    target_name = string_arg(tool_call.arguments, "tool_name") or string_arg(
        tool_call.arguments,
        "toolName",
    )
    target_name = target_name.strip()
    if not target_name:
        return run_tool_error("tool_name is required.", FAILURE_TOOL_NOT_INSTALLED)
    if target_name in AGENT_DYNAMIC_TOOL_NAMES:
        return run_tool_error(
            f"{AGENT_RUN_TOOL_TOOL_NAME} cannot invoke {target_name}.",
            FAILURE_TOOL_NOT_INSTALLED,
        )
    tool = tools.get(target_name)
    if tool is None:
        candidates = exact_name_matches(tools, target_name)
        if len(candidates) == 1:
            tool = candidates[0]
        elif len(candidates) > 1:
            return run_tool_error(
                "tool_name is ambiguous. Use the exact toolName returned by "
                f"{AGENT_SEARCH_TOOLS_TOOL_NAME}. Candidates: "
                f"{json.dumps([tool_search_result(candidate) for candidate in candidates])}"
            )
    if tool is None:
        blocked_tool = denied_tools.get(target_name)
        blocked_candidates = exact_name_matches(denied_tools, target_name)
        if blocked_tool is not None:
            blocked_candidates = [blocked_tool]
        if len(blocked_candidates) == 1:
            blocked = blocked_candidates[0]
            decision = denied.get(blocked.wire_name, (None, None))[1]
            policy_name = getattr(decision, "policy_name", "") or "workspace policy"
            return run_tool_error(
                (
                    f"{blocked.tool_schema.tool_name} is assigned to this agent but blocked "
                    f"by policy: {getattr(decision, 'message', '') or policy_name}"
                ),
                FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
                details=tool_policy_details(blocked, decision),
            )
        if len(blocked_candidates) > 1:
            candidates_json = json.dumps(
                [
                    tool_search_result(
                        candidate,
                        capability_status="assigned_blocked_policy",
                    )
                    for candidate in blocked_candidates
                ]
            )
            return run_tool_error(
                "tool_name is blocked by policy for multiple assigned tools. Use the exact "
                f"toolName returned by {AGENT_SEARCH_TOOLS_TOOL_NAME}. Candidates: "
                f"{candidates_json}",
                FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
            )
        installed_candidates = exact_installed_name_matches(
            installed_catalog_tools(catalog),
            target_name,
        )
        if installed_candidates:
            return run_tool_error(
                (
                    "tool_name is installed in this workspace but is not assigned to this "
                    "agent. Assign the connection/tool before running it."
                ),
                FAILURE_TOOL_INSTALLED_NOT_ASSIGNED,
                details={
                    "matches": [
                        installed_tool_search_result(candidate)
                        for candidate in installed_candidates[:5]
                    ]
                },
            )
        suggestions = [tool_search_result(match) for match in search_agent_tools(
            tools,
            query=target_name,
            limit=5,
        )]
        suffix = f" Suggestions: {json.dumps(suggestions)}" if suggestions else ""
        unavailable_message = (
            "tool_name is not installed in this workspace or no installed tool matches that "
            f"name. Call {AGENT_SEARCH_TOOLS_TOOL_NAME} to diagnose available capabilities."
            f"{suffix}"
        )
        return run_tool_error(
            unavailable_message,
            FAILURE_TOOL_NOT_INSTALLED,
        )
    raw_tool_args = tool_call.arguments.get("tool_args")
    if raw_tool_args is None:
        raw_tool_args = tool_call.arguments.get("toolArgs", {})
    if raw_tool_args is None:
        raw_tool_args = {}
    if not isinstance(raw_tool_args, dict):
        return run_tool_error("tool_args must be an object.")
    tool_args = normalize_agent_tool_args(tool, raw_tool_args)
    return (
        tool,
        AgentToolCall(
            name=tool.wire_name,
            call_id=tool_call.call_id,
            arguments=tool_args,
        ),
    )


def run_tool_error(
    message: str,
    failure_reason: str = FAILURE_TOOL_NOT_INSTALLED,
    *,
    details: dict[str, Any] | None = None,
) -> AgentToolExecutionResult:
    return tool_execution_result(
        AGENT_RUN_TOOL_TOOL_NAME,
        f"Tool {AGENT_RUN_TOOL_TOOL_NAME} failed: {message}",
        failure_reason=failure_reason,
        details=details,
    )


def normalize_agent_tool_args(
    tool: AgentRuntimeTool,
    raw_tool_args: dict[str, Any],
) -> dict[str, Any]:
    tool_args = dict(raw_tool_args)
    if should_strip_configured_target_arg(tool, tool_args):
        tool_args.pop("target", None)
    return tool_args


def should_strip_configured_target_arg(
    tool: AgentRuntimeTool,
    tool_args: dict[str, Any],
) -> bool:
    target = tool_args.get("target")
    if not isinstance(target, str):
        return False
    if "target" in required_schema_names(tool.tool_schema.input_schema):
        return False
    return normalize_search_text(target) == normalize_search_text(tool.installation.config_name)


def required_schema_names(schema: Any) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    required = schema.get("required")
    if not isinstance(required, list):
        return set()
    return {item for item in required if isinstance(item, str)}


def search_agent_tools(
    tools: dict[str, AgentRuntimeTool],
    *,
    query: str,
    limit: int,
) -> list[AgentRuntimeTool]:
    terms = query_terms(query)
    if not terms:
        return sorted(tools.values(), key=tool_sort_key)[:limit]
    scored = [
        (score_tool(tool, terms=terms, query=query), tool)
        for tool in tools.values()
    ]
    matches = [
        (score, tool)
        for score, tool in scored
        if score > 0
    ]
    matches.sort(key=lambda item: (-item[0], tool_sort_key(item[1])))
    return [tool for _score, tool in matches[:limit]]


def score_agent_tool_match(tool: AgentRuntimeTool, *, query: str) -> int:
    terms = query_terms(query)
    if not terms:
        return 0
    return score_tool(tool, terms=terms, query=query)


def search_hint(
    tools: dict[str, AgentRuntimeTool],
    *,
    denied_tools: dict[str, AgentRuntimeTool] | None = None,
    unassigned_tools: dict[str, AgentInstalledTool] | None = None,
    query: str,
    matches: list[AgentRuntimeTool],
    blocked_matches: list[AgentRuntimeTool] | None = None,
    unassigned_matches: list[AgentInstalledTool] | None = None,
) -> str | None:
    denied_tools = denied_tools or {}
    unassigned_tools = unassigned_tools or {}
    blocked_matches = blocked_matches or []
    unassigned_matches = unassigned_matches or []
    if not tools and not denied_tools and not unassigned_tools:
        return "No MCP tools are installed in this workspace."
    if matches:
        return None
    if blocked_matches:
        return (
            "Matching tools are assigned to this agent but blocked by policy. Do not fall "
            "back to another tool family; report the policy block."
        )
    if unassigned_matches:
        return (
            "Matching tools are installed but not assigned to this agent. Do not claim the "
            "tool is missing; report that it needs assignment."
        )
    terms = query_terms(query)
    if not terms:
        return "Use capability, product, and target keywords to search installed tools."
    return (
        "No installed, assigned, or policy-blocked tool matched those keywords. Try a "
        "different capability, product, or configured target name."
    )


def score_tool(tool: AgentRuntimeTool, *, terms: list[str], query: str) -> int:
    query_text = normalize_search_text(query)
    fields = [
        (10, tool.wire_name),
        (8, tool.tool_schema.tool_name),
        (7, tool.tool_schema.title or ""),
        (5, tool.installation.config_name),
        (4, tool.tool_schema.server_name),
        (4, tool.server.name),
        (2, tool.tool_schema.description or ""),
        (2, tool.server.description or ""),
        (1, schema_search_text(tool.tool_schema.input_schema)),
    ]
    score = 0
    for weight, value in fields:
        text = normalize_search_text(value)
        if not text:
            continue
        if query_text and query_text in text:
            score += weight * 4
        for term in terms:
            if term_matches_text(term, text):
                score += weight
    return score


def term_matches_text(term: str, text: str) -> bool:
    if term in text:
        return True
    if term.endswith("s") and len(term) > 4 and term[:-1] in text:
        return True
    return f"{term}s" in text


def query_terms(query: str) -> list[str]:
    tokens = normalize_search_text(query).split()
    terms = [
        token
        for token in tokens
        if len(token) >= 2 and token not in SEARCH_STOP_WORDS
    ]
    if terms:
        return terms
    return [token for token in tokens if len(token) >= 2]


def normalize_search_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def schema_search_text(schema: Any) -> str:
    chunks: list[str] = []

    def visit(value: Any, *, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    chunks.append(key)
                if isinstance(item, (dict, list)):
                    visit(item, depth=depth + 1)
                elif isinstance(item, str):
                    chunks.append(item)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth=depth + 1)

    visit(schema)
    return " ".join(chunks)


def tool_search_result(
    tool: AgentRuntimeTool,
    *,
    capability_status: str = "allowed",
    decision: Any | None = None,
) -> dict[str, Any]:
    result = {
        "capabilityStatus": capability_status,
        "canRun": capability_status == "allowed",
        "failureReason": (
            FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY
            if capability_status == "assigned_blocked_policy"
            else None
        ),
        "reason": (
            "Tool is assigned but blocked by policy."
            if capability_status == "assigned_blocked_policy"
            else "Tool is assigned, allowed, and available to run."
        ),
    }
    if decision is not None:
        result["policy"] = {
            "mode": getattr(decision, "mode", ""),
            "policyId": str(getattr(decision, "policy_id", "") or ""),
            "policyName": getattr(decision, "policy_name", ""),
            "message": getattr(decision, "message", ""),
            "matchedPolicyIds": [
                str(policy_id)
                for policy_id in getattr(decision, "matched_policy_ids", []) or []
            ],
        }
    result.update(
        {
            "toolName": tool.wire_name,
            "mcpToolName": tool.tool_schema.tool_name,
            "title": tool.tool_schema.title or tool.tool_schema.tool_name,
            "description": truncate_text(tool.tool_schema.description or "", 700),
            "serverName": tool.tool_schema.server_name,
            "configuredTarget": tool.installation.config_name,
            "configuredTargetHint": (
                "Wardn uses configuredTarget to route to this MCP installation. Do not pass "
                "configuredTarget as a target tool argument unless that exact in-tool target is "
                "separately required."
            ),
            "installationId": str(tool.installation.id),
            "toolSchemaId": str(tool.tool_schema.id),
            "readOnly": read_only_hint(tool),
            "params": summarize_input_schema(tool.tool_schema.input_schema),
        }
    )
    return result


def installed_tool_search_result(tool: AgentInstalledTool) -> dict[str, Any]:
    return {
        "capabilityStatus": "installed_not_assigned",
        "canRun": False,
        "failureReason": FAILURE_TOOL_INSTALLED_NOT_ASSIGNED,
        "reason": "Tool is installed in this workspace but not assigned to this agent.",
        "toolName": "",
        "mcpToolName": tool.tool_schema.tool_name,
        "title": tool.tool_schema.title or tool.tool_schema.tool_name,
        "description": truncate_text(tool.tool_schema.description or "", 700),
        "serverName": tool.tool_schema.server_name,
        "configuredTarget": tool.installation.config_name,
        "configuredTargetHint": (
            "Wardn uses configuredTarget to route to this MCP installation. Do not pass "
            "configuredTarget as a target tool argument unless that exact in-tool target is "
            "separately required."
        ),
        "installationId": str(tool.installation.id),
        "toolSchemaId": str(tool.tool_schema.id),
        "readOnly": installed_read_only_hint(tool),
        "params": summarize_input_schema(tool.tool_schema.input_schema),
    }


def summarize_input_schema(schema: Any) -> list[dict[str, Any]]:
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    params = []
    for name, value in properties.items():
        if not isinstance(name, str):
            continue
        value_record = value if isinstance(value, dict) else {}
        params.append(
            {
                "name": name,
                "required": name in required_names,
                "type": schema_type_text(value_record),
                "description": truncate_text(str(value_record.get("description") or ""), 220),
            }
        )
    return params


def schema_type_text(schema: dict[str, Any]) -> str:
    value = schema.get("type")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "|".join(str(item) for item in value if isinstance(item, str)) or "unknown"
    if "enum" in schema:
        return "enum"
    return "unknown"


def exact_name_matches(
    tools: dict[str, AgentRuntimeTool],
    target_name: str,
) -> list[AgentRuntimeTool]:
    normalized = normalize_search_text(target_name)
    if not normalized:
        return []
    return [
        tool
        for tool in tools.values()
        if normalized in exact_names(tool)
    ]


def exact_installed_name_matches(
    tools: dict[str, AgentInstalledTool],
    target_name: str,
) -> list[AgentInstalledTool]:
    normalized = normalize_search_text(target_name)
    if not normalized:
        return []
    return [
        tool
        for tool in tools.values()
        if normalized in exact_installed_names(tool)
    ]


def exact_installed_names(tool: AgentInstalledTool) -> set[str]:
    values = {
        tool.tool_schema.tool_name,
        tool.tool_schema.title or "",
        f"{tool.installation.config_name} {tool.tool_schema.tool_name}",
        f"{tool.tool_schema.server_name} {tool.installation.config_name} "
        f"{tool.tool_schema.tool_name}",
    }
    return {normalize_search_text(value) for value in values if normalize_search_text(value)}


def exact_names(tool: AgentRuntimeTool) -> set[str]:
    values = {
        tool.wire_name,
        tool.tool_schema.tool_name,
        tool.tool_schema.title or "",
        f"{tool.installation.config_name} {tool.tool_schema.tool_name}",
        f"{tool.tool_schema.server_name} {tool.installation.config_name} "
        f"{tool.tool_schema.tool_name}",
    }
    return {normalize_search_text(value) for value in values if normalize_search_text(value)}


def tool_sort_key(tool: AgentRuntimeTool) -> tuple[str, str, str, str]:
    return (
        tool.installation.config_name,
        tool.tool_schema.server_name,
        tool.tool_schema.tool_name,
        tool.wire_name,
    )


def installed_tool_sort_key(tool: AgentInstalledTool) -> tuple[str, str, str, str]:
    return (
        tool.installation.config_name,
        tool.tool_schema.server_name,
        tool.tool_schema.tool_name,
        str(tool.tool_schema.id),
    )


def search_installed_tools(
    tools: dict[str, AgentInstalledTool],
    *,
    query: str,
    limit: int,
) -> list[AgentInstalledTool]:
    terms = query_terms(query)
    if not terms:
        return sorted(tools.values(), key=installed_tool_sort_key)[:limit]
    scored = [
        (score_installed_tool(tool, terms=terms, query=query), tool)
        for tool in tools.values()
    ]
    matches = [
        (score, tool)
        for score, tool in scored
        if score > 0
    ]
    matches.sort(key=lambda item: (-item[0], installed_tool_sort_key(item[1])))
    return [tool for _score, tool in matches[:limit]]


def score_installed_tool(tool: AgentInstalledTool, *, terms: list[str], query: str) -> int:
    query_text = normalize_search_text(query)
    fields = [
        (8, tool.tool_schema.tool_name),
        (7, tool.tool_schema.title or ""),
        (5, tool.installation.config_name),
        (4, tool.tool_schema.server_name),
        (2, tool.tool_schema.description or ""),
        (1, schema_search_text(tool.tool_schema.input_schema)),
    ]
    score = 0
    for weight, value in fields:
        text = normalize_search_text(value)
        if not text:
            continue
        if query_text and query_text in text:
            score += weight * 4
        for term in terms:
            if term_matches_text(term, text):
                score += weight
    return score


def read_only_hint(tool: AgentRuntimeTool) -> bool:
    annotations = tool.tool_schema.annotations
    return isinstance(annotations, dict) and annotations.get("readOnlyHint") is True


def installed_read_only_hint(tool: AgentInstalledTool) -> bool:
    annotations = tool.tool_schema.annotations
    return isinstance(annotations, dict) and annotations.get("readOnlyHint") is True


def tool_policy_details(tool: AgentRuntimeTool, decision: Any | None) -> dict[str, Any]:
    return {
        "toolName": tool.tool_schema.tool_name,
        "serverName": tool.server.name,
        "configuredTarget": tool.installation.config_name,
        "installationId": str(tool.installation.id),
        "toolSchemaId": str(tool.tool_schema.id),
        "policy": {
            "mode": getattr(decision, "mode", ""),
            "policyId": str(getattr(decision, "policy_id", "") or ""),
            "policyName": getattr(decision, "policy_name", ""),
            "message": getattr(decision, "message", ""),
            "matchedPolicyIds": [
                str(policy_id)
                for policy_id in getattr(decision, "matched_policy_ids", []) or []
            ],
        },
    }


def truncate_text(value: str, max_chars: int) -> str:
    text = " ".join(value.strip().split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + " ...[truncated]"


def string_arg(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    return value if isinstance(value, str) else ""


def bounded_limit(value: Any) -> int:
    if isinstance(value, bool):
        return AGENT_SEARCH_TOOLS_DEFAULT_LIMIT
    if isinstance(value, int):
        return max(1, min(value, AGENT_SEARCH_TOOLS_MAX_LIMIT))
    return AGENT_SEARCH_TOOLS_DEFAULT_LIMIT
