import json
import re
from typing import Any

from app.modules.agents.platform_tools import (
    ASK_WARDN_PLATFORM_TOOL_NAME,
    ask_wardn_platform_tool_schema,
)
from app.modules.agents.skills import (
    WARDN_GET_SKILL_TOOL_NAME,
    WARDN_SEARCH_SKILLS_TOOL_NAME,
    skill_tool_capability_metadata,
)
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
    ASK_WARDN_PLATFORM_TOOL_NAME,
}
AGENT_SEARCH_TOOLS_DEFAULT_LIMIT = 8
AGENT_SEARCH_TOOLS_MAX_LIMIT = 20
TARGET_DISAMBIGUATION_ARG_NAMES = {
    "account",
    "account_name",
    "accountName",
    "cluster",
    "cluster_name",
    "clusterName",
    "configured_target",
    "configuredTarget",
    "repo",
    "repository",
    "repository_name",
    "repositoryName",
    "site",
    "site_name",
    "siteName",
    "target",
    "target_hint",
    "targetHint",
}
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


def agent_dynamic_function_tools(
    catalog: AgentToolCatalog,
    *,
    skill_tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    assigned_tool_count = len(allowed_catalog_tools(catalog)) + len(denied_catalog_tools(catalog))
    tools = [ask_wardn_platform_tool_schema()]
    if assigned_tool_count == 0 and not installed_catalog_tools(catalog) and not skill_tools:
        return tools
    tools.extend(
        [
        {
            "type": "function",
            "name": AGENT_SEARCH_TOOLS_TOOL_NAME,
            "description": (
                "Diagnose tool capability for this agent. Searches reachable Wardn tools, "
                "installed workspace MCP tools, policy-denied assigned MCP tools, and enabled "
                "Wardn Hub skill guidance capabilities. The "
                "response explains whether each relevant match is executable, installed but "
                "not assigned, or assigned but blocked by policy. Only returned tools with "
                "capabilityStatus=allowed can be passed to run_tool. Search by capability, "
                "system, and target; for example 'google search console gsc shipyardhq.dev', "
                "'kubernetes namespaces rancher-qa', 'github repo issues', or 'arxiv papers'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keywords for the capability and target, for example "
                            "'google search console gsc', 'kubernetes namespaces "
                            "rancher-qa', 'github repo issues', or 'arxiv read paper'."
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
                "Execute one MCP tool or read-only Wardn skill capability available to this "
                "agent. Use the exact toolName returned "
                f"by {AGENT_SEARCH_TOOLS_TOOL_NAME}; put the target tool arguments in tool_args. "
                "Do not copy configuredTarget into tool_args; Wardn uses configuredTarget to "
                "route to the configured MCP installation. "
                "The target tool is resolved server-side and evaluated by guardrail policies "
                "again immediately before execution. Wardn skill results are advisory and do "
                "not bypass MCP access rules."
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
                    "target_hint": {
                        "type": "string",
                        "description": (
                            "Optional configured target, cluster, account, repository, or "
                            "site hint used only by Wardn to disambiguate identical tool "
                            "names across targets. This value is not passed to the target tool."
                        ),
                    },
                    "configured_target": {
                        "type": "string",
                        "description": (
                            "Exact configuredTarget returned by search_tools, when known. This "
                            "value is used only by Wardn for server-side routing."
                        ),
                    },
                },
                "required": ["tool_name"],
                "additionalProperties": False,
            },
        },
        ]
    )
    return tools


def is_agent_dynamic_tool_name(name: str) -> bool:
    return name in AGENT_DYNAMIC_TOOL_NAMES


def execute_agent_search_tools(
    catalog: AgentToolCatalog,
    tool_call: AgentToolCall,
    *,
    skill_tools: list[dict[str, Any]] | None = None,
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
    allowed_rankings = [
        {
            "kind": "mcp",
            "score": score,
            "sortKey": tool_sort_key(tool),
            "payload": tool_search_result(
                tool,
                capability_status="allowed",
                rank=rank,
                score=score,
            ),
        }
        for rank, (score, tool) in enumerate(
            rank_agent_tools(tools, query=query),
            start=1,
        )
    ]
    skill_rankings = [
        {
            "kind": "skill",
            "score": score,
            "sortKey": skill_tool_sort_key(skill_tool),
            "payload": skill_tool_search_result(
                skill_tool,
                query=query,
                rank=rank,
                score=score,
            ),
        }
        for rank, (score, skill_tool) in enumerate(
            rank_skill_tools(skill_tools or [], query=query),
            start=1,
        )
    ]
    executable_rankings = sorted(
        [*allowed_rankings, *skill_rankings],
        key=lambda item: (-item["score"], item["kind"], item["sortKey"]),
    )
    blocked_rankings = [
        (
            score,
            tool_search_result(
                tool,
                capability_status="assigned_blocked_policy",
                decision=denied_catalog_tools(catalog).get(tool.wire_name, (None, None))[1],
                rank=rank,
                score=score,
            ),
        )
        for rank, (score, tool) in enumerate(
            rank_agent_tools(denied_tools, query=query),
            start=1,
        )
    ]
    unassigned_rankings = [
        (
            score,
            installed_tool_search_result(
                tool,
                rank=rank,
                score=score,
            ),
        )
        for rank, (score, tool) in enumerate(
            rank_installed_tools(unassigned_tools, query=query),
            start=1,
        )
    ]
    executable_matches = executable_rankings[:limit]
    executable_mcp_matches = [
        item for item in executable_matches if item["payload"].get("toolType") == "mcp"
    ]
    executable_skill_matches = [
        item for item in executable_matches if item["payload"].get("toolType") == "skill"
    ]
    blocked_matches = blocked_rankings[:limit]
    unassigned_matches = unassigned_rankings[:limit]
    output = {
        "query": query,
        "totalInstalled": len(installed_catalog_tools(catalog)) or len(assigned_schema_ids),
        "totalAssigned": len(assigned_schema_ids),
        "totalAllowed": len(tools),
        "totalReachable": len(tools) + len(skill_tools or []),
        "totalBlockedByPolicy": len(denied_tools),
        "matchCount": len(executable_matches) + len(blocked_matches) + len(unassigned_matches),
        "mcpMatchCount": len(executable_mcp_matches),
        "skillMatchCount": len(executable_skill_matches),
        "mcpMatches": [
            ranking_trace(item["payload"])
            for item in executable_mcp_matches[:AGENT_SEARCH_TOOLS_DEFAULT_LIMIT]
        ],
        "executionGuidance": search_execution_guidance(
            mcp_match_count=len(executable_mcp_matches),
            skill_match_count=len(executable_skill_matches),
            blocked_match_count=len(blocked_matches),
            unassigned_match_count=len(unassigned_matches),
        ),
        "tools": [item["payload"] for item in executable_matches],
        "blockedTools": [payload for _score, payload in blocked_matches],
        "unassignedTools": [payload for _score, payload in unassigned_matches],
        "hint": search_hint(
            tools,
            denied_tools=denied_tools,
            unassigned_tools=unassigned_tools,
            query=query,
            reachable_count=len(tools) + len(skill_tools or []),
            match_count=len(executable_matches),
            blocked_match_count=len(blocked_matches),
            unassigned_match_count=len(unassigned_matches),
        ),
        "ranking": {
            "query": query,
            "executable": [ranking_trace(item["payload"]) for item in executable_matches],
            "blockedByPolicy": [ranking_trace(payload) for _score, payload in blocked_matches],
            "unassigned": [ranking_trace(payload) for _score, payload in unassigned_matches],
            "omittedExecutable": max(len(executable_rankings) - len(executable_matches), 0),
            "omittedBlockedByPolicy": max(len(blocked_rankings) - len(blocked_matches), 0),
            "omittedUnassigned": max(len(unassigned_rankings) - len(unassigned_matches), 0),
        },
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
            "totalReachable": output["totalReachable"],
            "totalBlockedByPolicy": output["totalBlockedByPolicy"],
            "ranking": output["ranking"],
        },
    )


def resolve_agent_run_tool_call(
    catalog: AgentToolCatalog,
    tool_call: AgentToolCall,
    *,
    request_meta: dict[str, Any] | None = None,
) -> tuple[AgentRuntimeTool, AgentToolCall] | AgentToolExecutionResult:
    tools = allowed_catalog_tools(catalog)
    denied = denied_catalog_tools(catalog)
    denied_tools = {wire_name: tool for wire_name, (tool, _decision) in denied.items()}
    target_name = run_tool_target_name(tool_call.arguments)
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
            tool = disambiguate_tool_candidates(
                candidates,
                tool_call,
                request_meta=request_meta,
            )
        if tool is None and len(candidates) > 1:
            return run_tool_error(
                "tool_name is ambiguous. Use the exact toolName returned by "
                f"{AGENT_SEARCH_TOOLS_TOOL_NAME}. Candidates: "
                f"{json.dumps([tool_search_result(candidate) for candidate in candidates])}",
                details={
                    "targetDisambiguation": target_disambiguation_details(
                        candidates,
                        tool_call,
                        request_meta=request_meta,
                    )
                },
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
            blocked = disambiguate_tool_candidates(
                blocked_candidates,
                tool_call,
                request_meta=request_meta,
            )
            if blocked is not None:
                decision = denied.get(blocked.wire_name, (None, None))[1]
                policy_name = getattr(decision, "policy_name", "") or "workspace policy"
                return run_tool_error(
                    (
                        f"{blocked.tool_schema.tool_name} is assigned to this agent but "
                        f"blocked by policy: {getattr(decision, 'message', '') or policy_name}"
                    ),
                    FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
                    details=tool_policy_details(blocked, decision),
                )
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
                details={
                    "targetDisambiguation": target_disambiguation_details(
                        blocked_candidates,
                        tool_call,
                        request_meta=request_meta,
                    )
                },
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
    raw_tool_args = run_tool_arguments(tool_call.arguments)
    if raw_tool_args is None:
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


def run_tool_target_name(arguments: dict[str, Any]) -> str:
    return string_arg(arguments, "tool_name") or string_arg(arguments, "toolName")


def run_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any] | None:
    raw_tool_args = arguments.get("tool_args")
    if raw_tool_args is None:
        raw_tool_args = arguments.get("toolArgs", {})
    if raw_tool_args is None:
        raw_tool_args = {}
    return raw_tool_args if isinstance(raw_tool_args, dict) else None


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
    return [tool for _score, tool in rank_agent_tools(tools, query=query)[:limit]]


def rank_agent_tools(
    tools: dict[str, AgentRuntimeTool],
    *,
    query: str,
) -> list[tuple[int, AgentRuntimeTool]]:
    terms = query_terms(query)
    if not terms:
        return [(1, tool) for tool in sorted(tools.values(), key=tool_sort_key)]
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
    return matches


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
    reachable_count: int = 0,
    match_count: int = 0,
    blocked_match_count: int = 0,
    unassigned_match_count: int = 0,
) -> str | None:
    denied_tools = denied_tools or {}
    unassigned_tools = unassigned_tools or {}
    if not tools and not denied_tools and not unassigned_tools and reachable_count == 0:
        return "No MCP tools are installed in this workspace."
    if match_count:
        return None
    if blocked_match_count:
        return (
            "Matching tools are assigned to this agent but blocked by policy. Do not fall "
            "back to another tool family; report the policy block."
        )
    if unassigned_match_count:
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


def search_execution_guidance(
    *,
    mcp_match_count: int,
    skill_match_count: int,
    blocked_match_count: int,
    unassigned_match_count: int,
) -> str:
    if mcp_match_count:
        return (
            "Executable MCP tools matched this query. Use run_tool with an exact toolName "
            "from tools or mcpMatches; do not report the MCP server unavailable unless that "
            "run_tool call fails."
        )
    if blocked_match_count:
        return "Matching MCP tools are assigned but blocked by policy."
    if unassigned_match_count:
        return "Matching MCP tools are installed but not assigned to this agent."
    if skill_match_count:
        return (
            "Only Wardn Hub skill guidance matched this query. Skills are advisory; search "
            "again for the concrete MCP capability before claiming no MCP tool exists."
        )
    return "No executable MCP tool or skill matched this query."


def score_tool(tool: AgentRuntimeTool, *, terms: list[str], query: str) -> int:
    query_text = normalize_search_text(query)
    fields = [
        (10, tool.wire_name),
        (8, tool.tool_schema.tool_name),
        (7, tool.tool_schema.title or ""),
        (5, tool.installation.config_name),
        (4, searchable_server_name(tool.tool_schema.server_name)),
        (4, searchable_server_name(tool.server.name)),
        (2, tool.tool_schema.description or ""),
        (2, tool.server.description or ""),
        (1, schema_search_text(tool.tool_schema.input_schema)),
    ]
    score = 0
    score += server_identity_exact_score(
        tool.tool_schema.server_name,
        query_text=query_text,
        weight=4,
    )
    score += server_identity_exact_score(
        tool.server.name,
        query_text=query_text,
        weight=4,
    )
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


def searchable_server_name(value: Any) -> str:
    text = str(value or "")
    for prefix in ("io.github.",):
        if text.casefold().startswith(prefix):
            return text[len(prefix):]
    return text


def server_identity_exact_score(value: Any, *, query_text: str, weight: int) -> int:
    if len(query_text.split()) < 3:
        return 0
    text = normalize_search_text(value)
    if query_text and query_text in text:
        return weight * 4
    return 0


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
    rank: int | None = None,
    score: int | None = None,
) -> dict[str, Any]:
    result = {
        "toolType": "mcp",
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
            "rank": rank,
            "score": score,
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


def skill_tool_search_result(
    tool: dict[str, Any],
    *,
    query: str = "",
    rank: int | None = None,
    score: int | None = None,
) -> dict[str, Any]:
    tool_name = str(tool.get("name") or "")
    description = str(tool.get("description") or "")
    result = {
        "toolType": "skill",
        "capabilityStatus": "allowed",
        "canRun": True,
        "failureReason": None,
        "reason": "Tool is enabled for this agent and available to run.",
        "rank": rank,
        "score": score,
        "toolName": tool_name,
        "mcpToolName": "",
        "title": skill_tool_title(tool_name),
        "description": truncate_text(description, 700),
        "serverName": "wardn-hub-skills",
        "configuredTarget": "wardn-hub",
        "configuredTargetHint": (
            "This is a Wardn internal skill tool. Wardn runs it directly; it is not routed "
            "through an MCP installation."
        ),
        "installationId": "",
        "toolSchemaId": tool_name,
        "readOnly": True,
        "params": summarize_input_schema(tool.get("parameters")),
        "skill": skill_tool_capability_metadata(tool_name),
    }
    matches = approved_skill_matches_for_query(tool.get("approvedSkills"), query=query)
    if matches:
        result["approvedSkillMatches"] = matches
    return result


def installed_tool_search_result(
    tool: AgentInstalledTool,
    *,
    rank: int | None = None,
    score: int | None = None,
) -> dict[str, Any]:
    return {
        "toolType": "mcp",
        "capabilityStatus": "installed_not_assigned",
        "canRun": False,
        "failureReason": FAILURE_TOOL_INSTALLED_NOT_ASSIGNED,
        "reason": "Tool is installed in this workspace but not assigned to this agent.",
        "rank": rank,
        "score": score,
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


def disambiguate_tool_candidates(
    candidates: list[AgentRuntimeTool],
    tool_call: AgentToolCall,
    *,
    request_meta: dict[str, Any] | None = None,
) -> AgentRuntimeTool | None:
    target_text = target_disambiguation_text(tool_call, request_meta=request_meta)
    if not target_text:
        return None
    scored = [
        (target_match_score(candidate, target_text), candidate)
        for candidate in candidates
    ]
    scored = [(score, candidate) for score, candidate in scored if score > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], tool_sort_key(item[1])))
    best_score = scored[0][0]
    best = [candidate for score, candidate in scored if score == best_score]
    if len({candidate.installation.id for candidate in best}) != 1:
        return None
    return best[0]


def target_disambiguation_details(
    candidates: list[AgentRuntimeTool],
    tool_call: AgentToolCall,
    *,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_text = target_disambiguation_text(tool_call, request_meta=request_meta)
    return {
        "targetHint": target_text,
        "candidateCount": len(candidates),
        "candidates": [
            {
                "toolName": candidate.wire_name,
                "mcpToolName": candidate.tool_schema.tool_name,
                "serverName": candidate.server.name,
                "configuredTarget": candidate.installation.config_name,
                "installationId": str(candidate.installation.id),
                "score": target_match_score(candidate, target_text) if target_text else 0,
            }
            for candidate in sorted(candidates, key=tool_sort_key)
        ],
    }


def target_disambiguation_text(
    tool_call: AgentToolCall,
    *,
    request_meta: dict[str, Any] | None = None,
) -> str:
    chunks = []
    for key in TARGET_DISAMBIGUATION_ARG_NAMES:
        value = tool_call.arguments.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append(value)
    tool_args = run_tool_arguments(tool_call.arguments)
    if isinstance(tool_args, dict):
        for key in TARGET_DISAMBIGUATION_ARG_NAMES:
            value = tool_args.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value)
    request_text = (request_meta or {}).get("userMessage")
    if isinstance(request_text, str) and request_text.strip():
        chunks.append(request_text)
    return normalize_search_text(" ".join(chunks))


def target_match_score(tool: AgentRuntimeTool, target_text: str) -> int:
    if not target_text:
        return 0
    score = 0
    for raw_value, exact_weight, token_weight in (
        (tool.installation.config_name, 100, 15),
        (tool.tool_schema.server_name, 30, 6),
        (tool.server.name, 30, 6),
    ):
        normalized = normalize_search_text(raw_value)
        if not normalized:
            continue
        if normalized in target_text:
            score += exact_weight
        target_tokens = {
            token
            for token in normalized.split()
            if len(token) >= 2 and token not in SEARCH_STOP_WORDS
        }
        if target_tokens:
            score += token_weight * len(target_tokens & set(target_text.split()))
    return score


def selection_trace_details(
    catalog: AgentToolCatalog,
    selected_tool: AgentRuntimeTool,
    tool_call: AgentToolCall,
    *,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_name = run_tool_target_name(tool_call.arguments)
    candidates = exact_name_matches(allowed_catalog_tools(catalog), target_name)
    if not candidates and target_name == selected_tool.wire_name:
        candidates = [selected_tool]
    return {
        "requestedToolName": target_name,
        "selected": {
            "toolName": selected_tool.tool_schema.tool_name,
            "wireName": selected_tool.wire_name,
            "serverName": selected_tool.server.name,
            "configuredTarget": selected_tool.installation.config_name,
            "installationId": str(selected_tool.installation.id),
            "toolSchemaId": str(selected_tool.tool_schema.id),
        },
        "targetDisambiguation": target_disambiguation_details(
            candidates,
            tool_call,
            request_meta=request_meta,
        ),
    }


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


def skill_tool_sort_key(tool: dict[str, Any]) -> tuple[str, str]:
    return ("skill", str(tool.get("name") or ""))


def search_installed_tools(
    tools: dict[str, AgentInstalledTool],
    *,
    query: str,
    limit: int,
) -> list[AgentInstalledTool]:
    return [tool for _score, tool in rank_installed_tools(tools, query=query)[:limit]]


def rank_installed_tools(
    tools: dict[str, AgentInstalledTool],
    *,
    query: str,
) -> list[tuple[int, AgentInstalledTool]]:
    terms = query_terms(query)
    if not terms:
        return [(1, tool) for tool in sorted(tools.values(), key=installed_tool_sort_key)]
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
    return matches


def rank_skill_tools(
    tools: list[dict[str, Any]],
    *,
    query: str,
) -> list[tuple[int, dict[str, Any]]]:
    terms = query_terms(query)
    if not terms:
        return [(1, tool) for tool in sorted(tools, key=skill_tool_sort_key)]
    scored = [
        (score_skill_tool(tool, terms=terms, query=query), tool)
        for tool in tools
    ]
    matches = [
        (score, tool)
        for score, tool in scored
        if score > 0
    ]
    matches.sort(key=lambda item: (-item[0], skill_tool_sort_key(item[1])))
    return matches


def score_installed_tool(tool: AgentInstalledTool, *, terms: list[str], query: str) -> int:
    query_text = normalize_search_text(query)
    fields = [
        (8, tool.tool_schema.tool_name),
        (7, tool.tool_schema.title or ""),
        (5, tool.installation.config_name),
        (4, searchable_server_name(tool.tool_schema.server_name)),
        (2, tool.tool_schema.description or ""),
        (1, schema_search_text(tool.tool_schema.input_schema)),
    ]
    score = 0
    score += server_identity_exact_score(
        tool.tool_schema.server_name,
        query_text=query_text,
        weight=4,
    )
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


def score_skill_tool(tool: dict[str, Any], *, terms: list[str], query: str) -> int:
    query_text = normalize_search_text(query)
    fields = [
        (8, tool.get("name") or ""),
        (7, skill_tool_title(str(tool.get("name") or ""))),
        (4, "wardn hub skills"),
        (2, tool.get("description") or ""),
        (1, schema_search_text(tool.get("parameters"))),
    ]
    score = 0
    tool_name = str(tool.get("name") or "")
    for weight, value in fields:
        text = normalize_search_text(value)
        if not text:
            continue
        if query_text and query_text in text:
            score += weight * 4
        for term in terms:
            if term_matches_text(term, text):
                score += weight
    score += score_approved_skill_context(tool.get("approvedSkills"), terms=terms, query=query)
    if tool_name == WARDN_SEARCH_SKILLS_TOOL_NAME and terms:
        # Skill search can improve specialized workflows even when no approved skill matches yet.
        score += 2
    return score


def skill_tool_title(tool_name: str) -> str:
    if tool_name == WARDN_SEARCH_SKILLS_TOOL_NAME:
        return "Search Wardn Hub skills"
    if tool_name == WARDN_GET_SKILL_TOOL_NAME:
        return "Fetch Wardn Hub skill"
    return tool_name.replace("_", " ").strip().title() or "Wardn skill"


def score_approved_skill_context(
    value: Any,
    *,
    terms: list[str],
    query: str,
) -> int:
    if not isinstance(value, list):
        return 0
    return max(
        (
            score_approved_skill(skill, terms=terms, query=query)
            for skill in value
            if isinstance(skill, dict)
        ),
        default=0,
    )


def score_approved_skill(
    skill: dict[str, Any],
    *,
    terms: list[str],
    query: str,
) -> int:
    query_text = normalize_search_text(query)
    fields = [
        (14, skill.get("skillId") or ""),
        (12, skill.get("name") or ""),
        (8, skill.get("source") or ""),
        (5, skill.get("sourceOwner") or ""),
        (5, skill.get("sourceName") or ""),
        (4, skill.get("description") or ""),
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


def approved_skill_matches_for_query(value: Any, *, query: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    terms = query_terms(query)
    if not terms:
        return []
    scored = [
        (score_approved_skill(skill, terms=terms, query=query), skill)
        for skill in value
        if isinstance(skill, dict)
    ]
    matches = [(score, skill) for score, skill in scored if score > 0]
    matches.sort(key=lambda item: (-item[0], approved_skill_sort_key(item[1])))
    return [
        approved_skill_match_result(skill, score=score)
        for score, skill in matches[:AGENT_SEARCH_TOOLS_DEFAULT_LIMIT]
    ]


def approved_skill_match_result(skill: dict[str, Any], *, score: int) -> dict[str, Any]:
    return {
        "skillId": str(skill.get("skillId") or ""),
        "workspaceSkillId": str(skill.get("workspaceSkillId") or ""),
        "name": str(skill.get("name") or skill.get("skillId") or ""),
        "description": truncate_text(str(skill.get("description") or ""), 500),
        "url": str(skill.get("url") or ""),
        "source": str(skill.get("source") or ""),
        "auditStatus": skill.get("auditStatus"),
        "auditScore": skill.get("auditScore"),
        "auditRank": skill.get("auditRank"),
        "score": score,
        "nextStep": (
            f"Run {AGENT_RUN_TOOL_TOOL_NAME} with tool_name={WARDN_SEARCH_SKILLS_TOOL_NAME!r} "
            "and a one-to-three-term query, then fetch the selected skill with "
            f"{WARDN_GET_SKILL_TOOL_NAME}."
        ),
    }


def approved_skill_sort_key(skill: dict[str, Any]) -> tuple[str, str]:
    return (str(skill.get("name") or ""), str(skill.get("skillId") or ""))


def ranking_trace(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": result.get("rank"),
        "score": result.get("score"),
        "toolType": result.get("toolType"),
        "toolName": result.get("toolName"),
        "mcpToolName": result.get("mcpToolName"),
        "serverName": result.get("serverName"),
        "configuredTarget": result.get("configuredTarget"),
        "capabilityStatus": result.get("capabilityStatus"),
        "failureReason": result.get("failureReason"),
    }


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
