"use client";

import { CheckCircle2, Loader2, Pencil, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MCPOperationJobRead } from "@/lib/api/generated/model";
import {
  organizationMcpCatalogDeleteSource,
  organizationMcpCatalogGetOperationJob,
  organizationMcpCatalogSyncSource,
} from "@/lib/api/generated/organization-mcp-catalog/organization-mcp-catalog";
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

function providerLabel(provider: string) {
  if (provider === "wardn_hub") {
    return "Wardn Hub";
  }
  if (provider === "official") {
    return "Official";
  }
  return "Custom";
}

function displayDate(value?: string | null) {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Never";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function CatalogSourcesClient({
  organizationId,
  sources: initialSources,
}: CatalogSourcesClientProps) {
  const [sources, setSources] = useState(initialSources);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const { waitForJob } = useOperationJobPoller();

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
      {error ? (
        <AsyncFeedback variant="error">{error}</AsyncFeedback>
      ) : null}
      {notice ? (
        <AsyncFeedback className="flex items-center gap-2" variant="success">
          <CheckCircle2 className="size-4" />
          {notice}
        </AsyncFeedback>
      ) : null}

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>URL</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Last sync</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-40 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    No catalog sources
                  </TableCell>
                </TableRow>
              ) : (
                sources.map((source) => (
                  <TableRow key={source.id}>
                    <TableCell>
                      <div className="font-medium">{source.name}</div>
                      {source.lastError ? (
                        <div className="mt-1 max-w-72 truncate text-xs text-red-700">
                          {source.lastError}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <span className="block max-w-80 truncate text-sm">{source.baseUrl}</span>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{providerLabel(source.provider)}</Badge>
                    </TableCell>
                    <TableCell>{displayDate(source.lastSuccessAt)}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={source.isEnabled ? "success" : "outline"}>
                          {source.isEnabled ? "Active" : "Inactive"}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        <Button
                          aria-label={`Sync ${source.name}`}
                          disabled={busyId !== null || !source.isEnabled}
                          onClick={() => syncSource(source)}
                          size="icon"
                          title="Sync"
                          type="button"
                          variant="outline"
                        >
                          {busyId === source.id ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <RefreshCw className="size-4" />
                          )}
                        </Button>
                        {busyId !== null ? (
                          <Button
                            aria-label={`Edit ${source.name}`}
                            disabled
                            size="icon"
                            title="Edit"
                            type="button"
                            variant="outline"
                          >
                            <Pencil className="size-4" />
                          </Button>
                        ) : (
                          <Button asChild size="icon" variant="outline">
                            <Link
                              aria-label={`Edit ${source.name}`}
                              href={`/org/${organizationId}/catalog/edit/${source.id}`}
                              title="Edit"
                            >
                              <Pencil className="size-4" />
                            </Link>
                          </Button>
                        )}
                        <Button
                          aria-label={`Delete ${source.name}`}
                          disabled={busyId !== null}
                          onClick={() => deleteSource(source)}
                          size="icon"
                          title="Delete"
                          type="button"
                          variant="outline"
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
