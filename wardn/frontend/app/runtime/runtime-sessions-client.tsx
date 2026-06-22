"use client";

import {
  Activity,
  AlertTriangle,
  CircleStop,
  Gauge,
  HeartPulse,
  History,
  RefreshCw,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import {
  FeedbackMessages,
  McpTableCard,
  responseErrorMessage,
} from "@/app/mcp/mcp-list-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  MCPRuntimeEventListResponse,
  MCPRuntimeEventRead,
  MCPRuntimeSessionHealthResponse,
  MCPRuntimeSessionListResponse,
  MCPRuntimeSessionRead,
  MCPRuntimeSummaryResponse,
} from "@/lib/api/generated/model";

type RuntimeSessionsClientProps = {
  initialSessions: MCPRuntimeSessionRead[];
  initialSummary: MCPRuntimeSummaryResponse | null;
  organizationId: string;
  workspaceId: string;
};

const activeStatuses = new Set(["pending", "starting", "running", "idle"]);
const eventPollIntervalMs = 5_000;
const runtimeEventLimit = 50;

const eventTypeLabels: Record<string, string> = {
  runtime_session_created: "Created",
  runtime_session_reused: "Reused",
  runtime_session_replaced: "Replaced",
  tool_call_started: "Tool started",
  tool_call_succeeded: "Tool succeeded",
  tool_call_failed: "Tool failed",
  runtime_session_stopped: "Stopped",
  runtime_reaper_stopped: "Reaped",
};

function apiBasePath(organizationId: string, workspaceId: string) {
  return `/api/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
    workspaceId
  )}/mcp/runtime/sessions`;
}

function statusVariant(status: string) {
  if (status === "running" || status === "idle") {
    return "success" as const;
  }
  if (status === "failed") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function healthVariant(status: string) {
  if (status === "ready") {
    return "success" as const;
  }
  if (status === "not_ready") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function fallbackSummary(sessions: MCPRuntimeSessionRead[]): MCPRuntimeSummaryResponse {
  const sessionStatusCounts = sessions.reduce<Record<string, number>>((counts, session) => {
    counts[session.status] = (counts[session.status] ?? 0) + 1;
    return counts;
  }, {});

  return {
    activeSessions: sessions.filter((session) => activeStatuses.has(session.status)).length,
    expiredSessions: sessionStatusCounts.expired ?? 0,
    failedSessions: sessionStatusCounts.failed ?? 0,
    idleSessions: sessionStatusCounts.idle ?? 0,
    recentServerErrors: sessions
      .filter((session) => session.lastError)
      .map((session) => ({
        failureCount: session.failureCount,
        lastError: session.lastError,
        lastErrorAt: session.lastUsedAt,
        serverName: session.serverName,
        serverVersion: session.serverVersion,
      })),
    sessionStatusCounts,
    staleActiveSessions: 0,
    stoppedSessions: sessionStatusCounts.stopped ?? 0,
    toolCalls: {
      failed: 0,
      recentFailed: 0,
      recentFailureRate: 0,
      recentTotal: 0,
      running: 0,
      succeeded: 0,
      total: 0,
    },
    totalSessions: sessions.length,
  };
}

function formatDate(value?: string | null) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function eventTypeLabel(eventType: string) {
  return eventTypeLabels[eventType] ?? eventType;
}

function orderedEventTypes(events: MCPRuntimeEventRead[]) {
  const seen = new Set(events.map((event) => event.eventType));
  return Object.keys(eventTypeLabels)
    .filter((eventType) => seen.has(eventType))
    .concat([...seen].filter((eventType) => !eventTypeLabels[eventType]).sort());
}

export function RuntimeSessionsClient({
  initialSessions,
  initialSummary,
  organizationId,
  workspaceId,
}: RuntimeSessionsClientProps) {
  const [sessions, setSessions] = useState<MCPRuntimeSessionRead[]>(initialSessions);
  const [summary, setSummary] = useState<MCPRuntimeSummaryResponse>(
    initialSummary ?? fallbackSummary(initialSessions)
  );
  const [eventsBySession, setEventsBySession] = useState<Record<string, MCPRuntimeEventRead[]>>(
    {}
  );
  const [healthBySession, setHealthBySession] = useState<
    Record<string, MCPRuntimeSessionHealthResponse>
  >({});
  const [eventFiltersBySession, setEventFiltersBySession] = useState<Record<string, string[]>>(
    {}
  );
  const [expandedSessionId, setExpandedSessionId] = useState("");
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const basePath = apiBasePath(organizationId, workspaceId);

  const sortedSessions = useMemo(
    () =>
      [...sessions].sort((left, right) => {
        const leftDate = left.lastUsedAt ?? left.startedAt ?? "";
        const rightDate = right.lastUsedAt ?? right.startedAt ?? "";
        return rightDate.localeCompare(leftDate);
      }),
    [sessions]
  );
  const latestServerError = summary.recentServerErrors[0];

  const expandedSession = useMemo(
    () => sessions.find((session) => session.id === expandedSessionId),
    [expandedSessionId, sessions]
  );

  const loadEvents = useCallback(
    async (
      sessionId: string,
      options: { showError?: boolean; showSpinner?: boolean } = {}
    ) => {
      if (options.showSpinner) {
        setIsMutating(true);
      }
      try {
        const response = await fetch(
          `${basePath}/${encodeURIComponent(sessionId)}/events?limit=${runtimeEventLimit}`,
          { cache: "no-store" }
        );
        if (!response.ok) {
          throw new Error(await responseErrorMessage(response, "Failed to load runtime events."));
        }
        const payload = (await response.json()) as MCPRuntimeEventListResponse;
        setEventsBySession((current) => ({ ...current, [sessionId]: payload.events }));
      } catch (caught) {
        if (options.showError) {
          setExpandedSessionId("");
          setError(caught instanceof Error ? caught.message : "Runtime events could not load.");
        }
      } finally {
        if (options.showSpinner) {
          setIsMutating(false);
        }
      }
    },
    [basePath]
  );

  async function fetchRuntimeSummary() {
    const response = await fetch(`${basePath.replace(/\/sessions$/, "")}/summary`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(await responseErrorMessage(response, "Failed to refresh runtime summary."));
    }
    return (await response.json()) as MCPRuntimeSummaryResponse;
  }

  useEffect(() => {
    if (!expandedSession || !activeStatuses.has(expandedSession.status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void loadEvents(expandedSession.id);
    }, eventPollIntervalMs);

    return () => window.clearInterval(timer);
  }, [expandedSession, loadEvents]);

  async function refreshSessions() {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const [sessionsResponse, nextSummary] = await Promise.all([
        fetch(basePath, { cache: "no-store" }),
        fetchRuntimeSummary(),
      ]);
      if (!sessionsResponse.ok) {
        throw new Error(await responseErrorMessage(sessionsResponse, "Failed to refresh sessions."));
      }
      const payload = (await sessionsResponse.json()) as MCPRuntimeSessionListResponse;
      setSessions(payload.sessions);
      setSummary(nextSummary);
      setEventsBySession({});
      setHealthBySession({});
      setEventFiltersBySession({});
      setExpandedSessionId("");
      setNotice("Runtime sessions refreshed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Runtime sessions could not refresh.");
    } finally {
      setIsMutating(false);
    }
  }

  async function stopSession(session: MCPRuntimeSessionRead) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${basePath}/${encodeURIComponent(session.id)}/stop`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to stop runtime session."));
      }
      const stopped = (await response.json()) as MCPRuntimeSessionRead;
      setSessions((current) =>
        current.map((item) => (item.id === stopped.id ? stopped : item))
      );
      setHealthBySession((current) => {
        const next = { ...current };
        delete next[session.id];
        return next;
      });
      try {
        setSummary(await fetchRuntimeSummary());
      } catch {
        setSummary((current) => current);
      }
      setNotice("Runtime session stopped.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Runtime session could not be stopped.");
    } finally {
      setIsMutating(false);
    }
  }

  async function checkHealth(session: MCPRuntimeSessionRead) {
    setIsMutating(true);
    setError("");
    setNotice("");
    setExpandedSessionId(session.id);
    try {
      const response = await fetch(`${basePath}/${encodeURIComponent(session.id)}/health`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to check runtime health."));
      }
      const payload = (await response.json()) as MCPRuntimeSessionHealthResponse;
      setHealthBySession((current) => ({ ...current, [session.id]: payload }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Runtime health could not load.");
    } finally {
      setIsMutating(false);
    }
  }

  async function toggleEvents(session: MCPRuntimeSessionRead) {
    if (expandedSessionId === session.id) {
      setExpandedSessionId("");
      return;
    }
    setError("");
    setNotice("");
    setExpandedSessionId(session.id);
    if (eventsBySession[session.id]) {
      return;
    }
    await loadEvents(session.id, { showError: true, showSpinner: true });
  }

  function toggleEventType(sessionId: string, eventType: string) {
    setEventFiltersBySession((current) => {
      const selected = current[sessionId] ?? [];
      const nextSelected = selected.includes(eventType)
        ? selected.filter((item) => item !== eventType)
        : [...selected, eventType];

      return { ...current, [sessionId]: nextSelected };
    });
  }

  function clearEventFilters(sessionId: string) {
    setEventFiltersBySession((current) => ({ ...current, [sessionId]: [] }));
  }

  return (
    <div className="space-y-4">
      <section className="grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm text-muted-foreground">Active sessions</div>
              <div className="mt-2 text-2xl font-semibold">{summary.activeSessions}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {summary.totalSessions} total
              </div>
            </div>
            <Activity className="size-5 text-muted-foreground" />
          </div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm text-muted-foreground">Stale active</div>
              <div className="mt-2 text-2xl font-semibold">{summary.staleActiveSessions}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {summary.failedSessions} failed
              </div>
            </div>
            <AlertTriangle className="size-5 text-muted-foreground" />
          </div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm text-muted-foreground">Tool calls</div>
              <div className="mt-2 text-2xl font-semibold">{summary.toolCalls.total}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {summary.toolCalls.succeeded} succeeded, {summary.toolCalls.failed} failed
              </div>
            </div>
            <Gauge className="size-5 text-muted-foreground" />
          </div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-sm text-muted-foreground">24h failure rate</div>
          <div className="mt-2 text-2xl font-semibold">
            {formatPercent(summary.toolCalls.recentFailureRate)}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {summary.toolCalls.recentFailed} of {summary.toolCalls.recentTotal} recent calls
          </div>
        </div>
      </section>

      {latestServerError ? (
        <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3">
          <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <div className="text-sm font-medium">
                Latest runtime error: {latestServerError.serverName}
              </div>
              <div className="truncate text-sm text-muted-foreground">
                {latestServerError.lastError}
              </div>
            </div>
            <div className="text-xs text-muted-foreground">
              {formatDate(latestServerError.lastErrorAt)}
            </div>
          </div>
        </div>
      ) : null}

      <div className="flex justify-end">
        <Button disabled={isMutating} onClick={refreshSessions} size="sm" type="button" variant="outline">
          <RefreshCw className="size-4" />
          Refresh
        </Button>
      </div>

      <FeedbackMessages error={error} notice={notice} />

      <McpTableCard>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[320px]">Server</TableHead>
              <TableHead className="w-[150px]">Provider</TableHead>
              <TableHead className="w-[130px]">Status</TableHead>
              <TableHead className="w-[210px]">Last used</TableHead>
              <TableHead className="w-[210px]">Expires</TableHead>
              <TableHead className="w-[120px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedSessions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                  No runtime sessions have been recorded for this workspace
                </TableCell>
              </TableRow>
            ) : (
              sortedSessions.map((session) => {
                const events = eventsBySession[session.id] ?? [];
                const isExpanded = expandedSessionId === session.id;
                const selectedEventTypes = eventFiltersBySession[session.id] ?? [];
                const eventTypes = orderedEventTypes(events);
                const filteredEvents =
                  selectedEventTypes.length === 0
                    ? events
                    : events.filter((event) => selectedEventTypes.includes(event.eventType));
                const health = healthBySession[session.id];
                const isLive =
                  isExpanded && activeStatuses.has(session.status) && Boolean(eventsBySession[session.id]);

                return (
                  <Fragment key={session.id}>
                    <TableRow>
                      <TableCell>
                        <div className="space-y-1">
                          <div className="font-medium">{session.serverName}</div>
                          <div className="text-xs text-muted-foreground">
                            {session.serverVersion}
                          </div>
                          {session.lastError ? (
                            <div className="text-xs text-destructive">{session.lastError}</div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="text-sm">{session.runtimeProvider}</div>
                        <div className="text-xs text-muted-foreground">{session.runtimeKind}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(session.status)}>{session.status}</Badge>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatDate(session.lastUsedAt)}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatDate(session.expiresAt)}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-2">
                          <Button
                            disabled={isMutating}
                            onClick={() => checkHealth(session)}
                            size="icon"
                            title="Check runtime health"
                            type="button"
                            variant="outline"
                          >
                            <HeartPulse className="size-4" />
                          </Button>
                          <Button
                            disabled={isMutating}
                            onClick={() => toggleEvents(session)}
                            size="icon"
                            title="Show runtime events"
                            type="button"
                            variant="outline"
                          >
                            <History className="size-4" />
                          </Button>
                          <Button
                            disabled={isMutating || !activeStatuses.has(session.status)}
                            onClick={() => stopSession(session)}
                            size="icon"
                            title="Stop runtime session"
                            type="button"
                            variant="outline"
                          >
                            <CircleStop className="size-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                    {isExpanded ? (
                      <TableRow>
                        <TableCell colSpan={6} className="bg-muted/20">
                          {health ? (
                            <div className="mb-3 flex flex-col gap-2 rounded-md border bg-card px-3 py-2 md:flex-row md:items-center md:justify-between">
                              <div className="flex min-w-0 items-center gap-2">
                                <Badge variant={healthVariant(health.status)}>
                                  {health.status}
                                </Badge>
                                <div className="truncate text-sm">{health.message}</div>
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {health.ready ? "Ready" : "Not ready"}
                              </div>
                            </div>
                          ) : null}
                          {events.length === 0 ? (
                            <div className="py-4 text-sm text-muted-foreground">
                              No runtime events recorded.
                            </div>
                          ) : (
                            <div className="space-y-3 py-2">
                              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                                <div className="flex flex-wrap items-center gap-2">
                                  {eventTypes.map((eventType) => {
                                    const isSelected = selectedEventTypes.includes(eventType);

                                    return (
                                      <Button
                                        aria-pressed={isSelected}
                                        className="h-7 rounded-sm px-2 text-xs"
                                        key={eventType}
                                        onClick={() => toggleEventType(session.id, eventType)}
                                        type="button"
                                        variant={isSelected ? "secondary" : "outline"}
                                      >
                                        {eventTypeLabel(eventType)}
                                      </Button>
                                    );
                                  })}
                                  {selectedEventTypes.length > 0 ? (
                                    <Button
                                      className="h-7 rounded-sm px-2 text-xs"
                                      onClick={() => clearEventFilters(session.id)}
                                      type="button"
                                      variant="ghost"
                                    >
                                      All
                                    </Button>
                                  ) : null}
                                </div>
                                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                                  {isLive ? (
                                    <>
                                      <span className="size-2 rounded-full bg-emerald-500" />
                                      Live
                                    </>
                                  ) : (
                                    "Static"
                                  )}
                                </div>
                              </div>

                              {filteredEvents.length === 0 ? (
                                <div className="rounded-md border bg-card px-3 py-4 text-sm text-muted-foreground">
                                  No events match the selected filters.
                                </div>
                              ) : null}

                              {filteredEvents.map((event) => (
                                <div
                                  className="grid gap-2 rounded-md border bg-card px-3 py-2 md:grid-cols-[220px_minmax(0,1fr)]"
                                  key={event.id}
                                >
                                  <div>
                                    <div className="text-sm font-medium">
                                      {eventTypeLabel(event.eventType)}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                      {event.eventType}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                      {formatDate(event.createdAt)}
                                    </div>
                                  </div>
                                  <div className="min-w-0 space-y-1">
                                    <div className="text-sm">{event.message}</div>
                                    {event.metadata &&
                                    Object.keys(event.metadata).length > 0 ? (
                                      <pre className="overflow-x-auto rounded border bg-muted px-2 py-1 text-xs text-muted-foreground">
                                        {JSON.stringify(event.metadata, null, 2)}
                                      </pre>
                                    ) : null}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </McpTableCard>
    </div>
  );
}
