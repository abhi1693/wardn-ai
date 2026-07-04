# Wardn Product Vision And Roadmap

Date: 2026-07-05

## Product Thesis

Wardn is the enterprise gateway for MCP servers. It gives organizations one
place to connect MCP servers, govern which agents can use them, enforce
guardrails before tools run, schedule recurring agent work, and inspect every
run with traceable evidence.

Wardn should not be just a catalog browser or chat UI. The durable product value
is controlled MCP execution:

```text
trusted MCP servers
  -> workspace installations
  -> externalized secrets
  -> governed gateway
  -> agents and scheduled tasks
  -> guardrails, traces, memory, and RAG
```

## Core Workflows

- Connect a catalog source such as Wardn Hub.
- Install MCP servers into a workspace.
- Store required credentials through an external secret backend.
- Bind whole MCP servers or selected tools to an agent.
- Chat with an agent through Wardn's MCP gateway.
- Create scheduled tasks that run agents with the same tool bindings.
- Apply guardrails that can allow, block, or require confirmation before MCP
  tool execution.
- Inspect agent runs, tool calls, runtime sessions, policy decisions, and
  errors.
- Attach knowledge sources and memory so agents can retrieve context through
  RAG before answering or taking action.

## Platform Layers

1. **Catalog and install control plane**
   - Organization catalog sources.
   - Workspace MCP server installations.
   - Runtime target metadata and validation.

2. **Secret and runtime boundary**
   - External secret stores, starting with OpenBao.
   - Kubernetes/k3s runtime execution for package and OCI servers.
   - Runtime sessions, events, and tool invocation records.

3. **MCP gateway**
   - One scoped execution boundary for agents and external clients.
   - Tool discovery, invocation, runtime selection, and audit tracking.

4. **Agents and runs**
   - Workspace agents with LLM credentials and MCP bindings.
   - Persisted conversations.
   - Agent runs and ordered run steps for model, tool, guardrail, retrieval, and
     error events.

5. **Guardrails**
   - Policy checks at the MCP invocation boundary.
   - Allow/deny/confirmation rules by org, workspace, agent, server, and tool.
   - Sanitized trace records for every policy decision.

6. **Scheduled tasks**
   - Recurring and one-off agent executions.
   - Same tool bindings, guardrails, traces, and secrets as chat.

7. **Knowledge and memory**
   - Workspace knowledge sources and ingestion status.
   - Agent/workspace memory.
   - Retrieval steps recorded in agent runs.

## Implementation Roadmap

### Phase 1: Agent Run Trace

Create durable run records for each chat turn and future automation trigger.
Every run should have ordered steps for model input, tool activity, model output,
and errors. This is the foundation for guardrails, scheduled tasks, and RAG
observability.

### Phase 2: Guardrails

Add policy storage and enforcement at the MCP invocation boundary. The first
guardrails should support tool allow/deny rules, destructive-action confirmation
requirements, and sensitive argument checks with redaction.

### Phase 3: Trace UI

Expose run traces from chat and runtime pages. Tool activity should link to a
run detail view with sanitized arguments, results, runtime status, guardrail
decisions, and errors.

### Phase 4: Scheduled Tasks

Add scheduled agent tasks that reuse the same execution path as chat. Scheduled
runs should create agent run records, emit run steps, and be debuggable through
the trace UI.

### Phase 5: Knowledge, Memory, And RAG

Add workspace knowledge sources, ingestion, retrieval, and memory. Retrieval
must be recorded as run steps so users can see what context was used.

## Product Principles

- Backend enforcement first; frontend checks are advisory only.
- Enabled means allowed, not necessarily running.
- Secret values must never be stored in chat parts, run steps, or trace UI.
- Scheduled and chat-triggered agents must share the same gateway and guardrail
  path.
- RAG and memory should be observable, not hidden prompt stuffing.
