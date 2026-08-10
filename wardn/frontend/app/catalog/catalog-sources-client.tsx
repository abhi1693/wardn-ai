"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Globe2,
  KeyRound,
  Loader2,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { StatusDot } from "@/components/atoms/status-dot";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { Card, CardContent, CardHeader } from "@/components/atoms/card";
import { Input } from "@/components/atoms/input";
import type { MCPOperationJobRead } from "@/lib/api/generated/model";
import {
  organizationMcpCatalogDeleteSource,
  organizationMcpCatalogGetOperationJob,
  organizationMcpCatalogSyncSource,
} from "@/lib/api/generated/organization-mcp-catalog/organization-mcp-catalog";
import { formatUserShortDateTime } from "@/lib/date-time";
import {
  isOperationJobPollingCancelled,
  useOperationJobPoller,
} from "@/lib/use-operation-job";

import type { MCPCatalogSource } from "./catalog-source-types";

type CatalogSourcesClientProps = {
  organizationId: string;
  sources: MCPCatalogSource[];
};

type CatalogSyncResult = {
  source: MCPCatalogSource;
  syncedCount: number;
};

type SourceFilter = "active" | "all" | "issues" | "paused";

function providerLabel(provider: string) {
  if (provider === "wardn_hub") {
    return "Wardn Hub";
  }
  if (provider === "official") {
    return "Official";
  }
  return "Custom";
}

function syncModeLabel(syncMode: string) {
  if (syncMode === "all_versions") {
    return "All versions";
  }
  if (syncMode === "latest_only") {
    return "Latest only";
  }
  return syncMode || "Default";
}

function displayDate(value?: string | null) {
  return formatUserShortDateTime(value, "Never synced");
}

function displayHost(value: string) {
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

function sourceTone(source: MCPCatalogSource) {
  if (source.lastError) {
    return "danger" as const;
  }
  if (!source.isEnabled) {
    return "neutral" as const;
  }
  if (sourceNeedsToken(source)) {
    return "warning" as const;
  }
  return "success" as const;
}

function sourceNeedsToken(source: MCPCatalogSource) {
  return source.provider === "wardn_hub" && !source.hasAuthToken;
}

function sourceStatusLabel(source: MCPCatalogSource) {
  if (source.lastError) {
    return "Issue";
  }
  if (!source.isEnabled) {
    return "Paused";
  }
  if (sourceNeedsToken(source)) {
    return "Needs token";
  }
  return "Active";
}

function sourceMatchesFilter(source: MCPCatalogSource, filter: SourceFilter) {
  if (filter === "all") {
    return true;
  }
  if (filter === "active") {
    return source.isEnabled && !source.lastError && !sourceNeedsToken(source);
  }
  if (filter === "issues") {
    return Boolean(source.lastError || sourceNeedsToken(source));
  }
  return !source.isEnabled;
}

function filterLabel(filter: SourceFilter) {
  if (filter === "all") {
    return "All";
  }
  if (filter === "active") {
    return "Active";
  }
  if (filter === "issues") {
    return "Issues";
  }
  return "Paused";
}

export function CatalogSourcesClient({
  organizationId,
  sources: initialSources,
}: CatalogSourcesClientProps) {
  const [sources, setSources] = useState(initialSources);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState<SourceFilter>("active");
  const [search, setSearch] = useState("");
  const { waitForJob } = useOperationJobPoller();

  const filteredSources = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sources
      .filter((source) => {
        const matchesQuery =
          !query ||
          source.name.toLowerCase().includes(query) ||
          source.baseUrl.toLowerCase().includes(query) ||
          providerLabel(source.provider).toLowerCase().includes(query);
        return matchesQuery && sourceMatchesFilter(source, filter);
      })
      .sort((first, second) => {
        if (first.lastError && !second.lastError) {
          return -1;
        }
        if (!first.lastError && second.lastError) {
          return 1;
        }
        if (first.isEnabled !== second.isEnabled) {
          return first.isEnabled ? -1 : 1;
        }
        return first.name.localeCompare(second.name);
      });
  }, [filter, search, sources]);

  const activeCount = sources.filter(
    (source) => source.isEnabled && !source.lastError && !sourceNeedsToken(source)
  ).length;
  const issueCount = sources.filter((source) => source.lastError || sourceNeedsToken(source)).length;
  const pausedCount = sources.filter((source) => !source.isEnabled).length;
  const neverSyncedCount = sources.filter((source) => !source.lastSuccessAt).length;
  const sourceSummaryItems = [
    { label: "total", value: sources.length },
    { label: "active", value: activeCount },
    { label: "issues", value: issueCount },
    { label: "paused", value: pausedCount },
    { label: "never synced", value: neverSyncedCount },
  ];

  async function syncSource(source: MCPCatalogSource) {
    setBusyId(source.id);
    setError("");
    setNotice("");
    try {
      const job = await organizationMcpCatalogSyncSource(organizationId, source.id);
      const payload = await waitForJob<CatalogSyncResult>({
        failureMessage: "Catalog synchronization failed.",
        fetchJob: (jobId, signal) =>
          organizationMcpCatalogGetOperationJob(organizationId, jobId, { signal }),
        initialJob: job,
        onProgress: setNotice,
        pendingMessage: "Catalog synchronization queued",
        readResult: (completedJob: MCPOperationJobRead) => {
          const result = completedJob.result;
          if (!result?.source || typeof result.syncedCount !== "number") {
            throw new Error("Catalog synchronization completed without a result.");
          }
          return result as CatalogSyncResult;
        },
        timeoutMessage: "Catalog synchronization is still running. Check again shortly.",
      });
      setSources((current) =>
        current.map((item) => (item.id === source.id ? payload.source : item))
      );
      setNotice(`Synced ${payload.syncedCount} server definitions.`);
    } catch (caught) {
      if (isOperationJobPollingCancelled(caught)) {
        return;
      }
      setError(caught instanceof Error ? caught.message : "Catalog sync failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteSource(source: MCPCatalogSource) {
    setBusyId(source.id);
    setError("");
    setNotice("");
    try {
      await organizationMcpCatalogDeleteSource(organizationId, source.id);
      setSources((current) => current.filter((item) => item.id !== source.id));
      setNotice("Catalog source deleted.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Catalog source could not be deleted.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold leading-5 text-foreground">Catalog sources</div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
            {sourceSummaryItems.map((item) => (
              <span
                aria-label={`${item.value} ${item.label}`}
                className="inline-flex h-6 items-center gap-1 rounded-sm border border-border bg-muted/60 px-2"
                key={item.label}
              >
                <span className="font-semibold text-foreground">
                  {item.value.toLocaleString("en-US")}
                </span>
                {item.label}
              </span>
            ))}
          </div>
        </div>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative min-w-0 sm:w-[320px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search sources"
              type="search"
              value={search}
            />
          </div>
          <div className="flex rounded-md border border-border bg-card p-1">
            {(["active", "issues", "paused", "all"] as SourceFilter[]).map((item) => (
              <Button
                className="h-7 px-2 text-xs"
                key={item}
                onClick={() => setFilter(item)}
                size="sm"
                type="button"
                variant={filter === item ? "secondary" : "ghost"}
              >
                {filterLabel(item)}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {error ? (
        <AsyncFeedback variant="error">{error}</AsyncFeedback>
      ) : null}
      {notice ? (
        <AsyncFeedback className="flex items-center gap-2" variant="success">
          <CheckCircle2 className="size-4" />
          {notice}
        </AsyncFeedback>
      ) : null}

      {filteredSources.length === 0 ? (
        <Card className="flex min-h-60 flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="flex size-10 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
            <Globe2 className="size-5" />
          </div>
          <div>
            <div className="font-medium text-foreground">No catalog sources in view</div>
            <div className="mt-1 text-sm text-muted-foreground">No matching source feeds.</div>
          </div>
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${encodeURIComponent(organizationId)}/catalog/new`}>
              Add source
            </Link>
          </Button>
        </Card>
      ) : (
        <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredSources.map((source) => {
            const tone = sourceTone(source);
            const isBusy = busyId === source.id;
            return (
              <Card
                aria-label={`${source.name} catalog source`}
                className="flex min-h-[248px] flex-col overflow-hidden transition-colors hover:border-ring/40 hover:bg-muted/20"
                key={source.id}
                role="article"
              >
                <CardHeader className="border-b-0 pb-0">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <StatusDot tone={tone} />
                        <h3 className="truncate text-sm font-semibold leading-5 text-foreground">
                          {source.name}
                        </h3>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge
                          variant={
                            tone === "danger"
                              ? "destructive"
                              : tone === "success"
                                ? "success"
                                : "secondary"
                          }
                        >
                          {sourceStatusLabel(source)}
                        </Badge>
                        <Badge variant="outline">{providerLabel(source.provider)}</Badge>
                      </div>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="flex flex-1 flex-col p-4 pt-3">
                  <div className="flex min-w-0 items-center gap-2 text-sm">
                    <Globe2 className="size-4 shrink-0 text-muted-foreground" />
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="truncate">{displayHost(source.baseUrl)}</span>
                      <a
                        className="inline-flex shrink-0 items-center gap-1 text-foreground underline-offset-4 hover:underline"
                        href={source.baseUrl}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Open
                        <ExternalLink className="size-3.5" />
                      </a>
                    </div>
                  </div>

                  {source.lastError ? (
                    <div className="mt-4 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm leading-5 text-red-700">
                      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                      <span className="min-w-0 break-words">{source.lastError}</span>
                    </div>
                  ) : null}

                  <div className="mt-4 grid gap-3 border-y border-border/80 py-3">
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <Clock3 className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Last sync</div>
                        <div className="truncate text-sm font-medium">
                          {displayDate(source.lastSuccessAt)}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <RefreshCw className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Sync mode</div>
                        <div className="truncate text-sm font-medium">
                          {syncModeLabel(source.syncMode)}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <KeyRound className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Auth token</div>
                        <div className="truncate text-sm font-medium">
                          {source.hasAuthToken ? "Configured" : "Missing"}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
                    <Button
                      aria-label={`Sync ${source.name}`}
                      disabled={busyId !== null || !source.isEnabled}
                      onClick={() => syncSource(source)}
                      size="sm"
                      title="Sync"
                      type="button"
                      variant="secondary"
                    >
                      {isBusy ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <RefreshCw className="size-4" />
                      )}
                      Sync
                    </Button>
                    {busyId !== null ? (
                      <Button
                        aria-label={`Edit ${source.name}`}
                        disabled
                        size="sm"
                        title="Edit"
                        type="button"
                        variant="outline"
                      >
                        <Pencil className="size-4" />
                        Edit
                      </Button>
                    ) : (
                      <Button asChild size="sm" variant="outline">
                        <Link
                          aria-label={`Edit ${source.name}`}
                          href={`/org/${encodeURIComponent(
                            organizationId
                          )}/catalog/edit/${encodeURIComponent(source.id)}`}
                          title="Edit"
                        >
                          <Pencil className="size-4" />
                          Edit
                        </Link>
                      </Button>
                    )}
                    <Button
                      className="sm:ml-auto"
                      aria-label={`Delete ${source.name}`}
                      disabled={busyId !== null}
                      onClick={() => deleteSource(source)}
                      size="sm"
                      title="Delete"
                      type="button"
                      variant="ghost"
                    >
                      <Trash2 className="size-4" />
                      Delete
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
