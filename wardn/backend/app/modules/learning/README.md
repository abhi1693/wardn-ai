# Execution evidence: Milestone 1

This module records observable Wardn actions in PostgreSQL. It does not run reflection,
embeddings, episode generation, retrieval or skill synthesis. Nothing is published to Wardn Hub.
Provider implementations and guardrail decisions remain unchanged.

## Schema and identity

Migration `202609070001` adds:

| Table | Purpose |
| --- | --- |
| `learning_events` | Append-only, workspace-scoped events with typed vocabulary and provenance |
| `learning_event_streams` | Transactional workspace sequence allocator |
| `learning_worker_cursors` | One resumable checkpoint per workspace and named consumer |

An agent execution uses `AgentRun.id`; conversations keep `WorkspaceConversation.id`.
Scheduled orchestration uses `WorkspaceScheduledTaskRun.id`, including failures before an agent
exists, retries, approvals and delivery failures. Its agent execution has a separate agent-run
ID, and every agent event carries the originating `scheduled_run_id` and `scheduled_task_id`.
This distinguishes successful agent work from failed delivery. A direct gateway invocation
without an agent uses `MCPToolInvocation.id` as its execution ID. `execution_kind` disambiguates
these existing identities. MCP events always carry the real invocation UUID as `tool_call_id`.
Provider call IDs are retained as metadata when available, not converted into new UUIDs.
`objective_id` is reserved, optional and not inferred from conversations.

Events have contiguous `sequence_number` values within an execution and monotonically increasing
`workspace_sequence` values for consumers. Unique constraints prevent duplicate execution
sequences, workspace sequences and source idempotency keys. A retry returns the original event;
it never updates its data. Retrying an idempotency key can leave a workspace sequence gap.

The workspace allocator uses a PostgreSQL row lock held until the source transaction commits.
Unlike a database sequence or timestamp watermark, later writers cannot commit a higher cursor
value ahead of an earlier uncommitted writer. Consumers therefore cannot silently skip events.
This serializes event-writing transactions within a workspace; keep their transactions short.
It does not serialize unrelated workspaces or introduce a broker.

The emitter validates workspace ownership, existing execution identity and referenced entities.
Every repository read requires both organization and workspace. Database triggers enforce the
workspace/organization relationship and reject updates and ordinary deletes of events.
Provenance IDs are immutable snapshots rather than cascading source foreign keys, so existing
run/tool retention does not rewrite history. Explicit workspace deletion cascades to its learning
data. There is no independent event-retention/pruning job in this milestone.

## Capture points

| Existing code | Evidence |
| --- | --- |
| `agents/repository.py` | Run start, status transitions, persisted user/assistant messages, stateless model input/output references, approval requests and decisions, guardrail evaluation references |
| `agents/chat_orchestrator.py` | Streamed response persistence, cancellation and external Hub snapshot ID/hash metadata |
| `mcp_runtime/service.py` | Tool selection/start, completion, protocol error results, transport failure, stale-invocation recovery; shared by agent and gateway calls |
| `agents/tool_execution.py` | Result handoff to agent orchestration, linked to the invocation |
| `scheduled_tasks/repository.py` | Claims, retries, lease recovery, approval waits, cancellation and terminal/delivery outcomes |
| `scheduled_tasks/service.py`, `agents/service.py`, `agents/capacity.py` | Propagate scheduled-run identity through ordinary and hosted-cloud run creation |

Writes use the source session and commit/roll back with the original action. MCP isolated
tracking commits the start before invoking the remote tool and commits the result separately,
as it already did. Agent result handoff uses a fresh short transaction after that tracking
transaction closes. A remote side effect cannot be rolled back: a crash between remote completion
and local finalization remains an unknown outcome until existing stale-call recovery records a
failure. `tool.result_observed` means the result was handed back to the agent orchestration
boundary; it does not assert access to the model's private interpretation.

Run success records Wardn's existing execution status, not proof that a user's business objective
was achieved. Future learning consumers must distinguish execution success from user feedback.
No correction classifier is added; the typed emitter supports explicit feedback/correction/
preference events when a caller has that signal. There is no new public event-ingestion endpoint.

## Privacy and payloads

Default capture stores bounded metadata, identifiers, tool names, status, timing and size counts.
User/assistant text, arguments, raw tool results and approval content are not copied into events.
`source_ref` identifies the existing record; message/run-step content can be inspected through
existing authorized Wardn interfaces. Invocation records contain metrics, not archived raw tool
results, so a reference does not promise recovery of the original raw result after the fact.
Future learning consumers must separately classify/redact any content read from source records.

The shared Wardn redactor is reused, with additional private-key, basic-auth, credential URL,
JWT and sensitive-path handling, depth/collection bounds and a 16 KiB event-data budget.
Reasoning, reasoning summaries, analysis and scratchpad fields are excluded. Nothing requests
chain-of-thought. Optional explicit `agent.decision` records may contain a concise reason.
These safeguards do not make arbitrary source text safe to forward to a future learning model.

## Inspection and consumers

Apply migrations before enabling capture. `WARDN_LEARNING_EVENTS_ENABLED` defaults to `true`;
setting it to `false` stops automatic capture without removing existing events. There is no
backfill of pre-migration or disabled-period history.

Operators can inspect a bounded page without changing a cursor:

```sh
uv run python -m app.manage learningevents \
  --organization-id ORGANIZATION_UUID --workspace-id WORKSPACE_UUID \
  --execution-id AGENT_RUN_UUID --limit 100
```

Use the returned `next_after_sequence` as `--after-sequence` for the next page. This is a
database-operator command, not a public HTTP API. It never dereferences source payloads.

Future workers use the existing separate-process worker approach and call `consume_batch` inside
`async with session.begin()`. The callback writes derived state using that same session, without
committing or performing external side effects. Its writes and the cursor commit atomically.
Exceptions roll both back; concurrent workers serialize on the cursor row. Do not use this
transactional callback for LLM/network calls: a later milestone needs claimed jobs for those.
No idle/no-op production learning worker is added before a consumer exists.

## Verification and review questions

Unit tests cover vocabulary, timezone validation, secret classification, hidden reasoning and
payload bounds. PostgreSQL integration tests cover migrations, ordered/concurrent/idempotent
append, out-of-order commit prevention across executions, cursor replay/rollback/competition,
source transaction rollback, workspace isolation, database immutability, source retention and
workspace erasure, conversation/cancellation, MCP error/recovery and scheduled execution links.
Use `WARDN_TEST_DATABASE_URL` with the existing disposable-database fixture; it creates and drops
its own database rather than touching the configured application database.

Before Milestone 2, review source-content access and redaction policy, event retention duration,
allocator contention under real traffic, and the distinction between user-validated success and
runtime success. Trace/span columns accept existing trace IDs but capture does not invent them;
the current agent orchestration normally leaves those observability fields empty. Plans and
explicit feedback have typed vocabulary but no synthetic events are inferred from private
reasoning or free text. Existing successful Hub fetches record `skill.external_retrieved` with
the snapshot ID/hash, without copying skill content. No skill application or business-success
signal is inferred from retrieval alone; no internal learning registry is introduced here.
