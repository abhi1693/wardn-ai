"use client";

import { CheckCircle2, Loader2, Pencil, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
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

import type { MCPCatalogSource } from "./catalog-source-types";

type CatalogSourcesClientProps = {
  organizationId: string;
  sources: MCPCatalogSource[];
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

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

export function CatalogSourcesClient({
  organizationId,
  sources: initialSources,
}: CatalogSourcesClientProps) {
  const [sources, setSources] = useState(initialSources);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function syncSource(source: MCPCatalogSource) {
    setBusyId(source.id);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        `/api/organizations/${organizationId}/mcp/catalog/sources/${source.id}/sync`,
        { method: "POST" }
      );
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Catalog sync failed."));
      }
      const payload = (await response.json()) as {
        source: MCPCatalogSource;
        syncedCount: number;
      };
      setSources((current) =>
        current.map((item) => (item.id === source.id ? payload.source : item))
      );
      setNotice(`Synced ${payload.syncedCount} server definitions.`);
    } catch (caught) {
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
      const response = await fetch(
        `/api/organizations/${organizationId}/mcp/catalog/sources/${source.id}`,
        { method: "DELETE" }
      );
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Catalog source could not be deleted."));
      }
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
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          <CheckCircle2 className="size-4" />
          {notice}
        </div>
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
                        <Badge variant={source.hasAuthToken ? "secondary" : "outline"}>
                          {source.hasAuthToken ? "Token stored" : "No token"}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        <Button
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
                        <Button asChild disabled={busyId !== null} size="icon" variant="outline">
                          <Link href={`/org/${organizationId}/catalog/edit/${source.id}`} title="Edit">
                            <Pencil className="size-4" />
                          </Link>
                        </Button>
                        <Button
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
