"use client";

import {
  ChevronLeft,
  ChevronRight,
  Network,
  Package,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  FeedbackMessages,
  McpTableCard,
  RuntimeBadge,
  ServerIdentityCell,
  responseErrorMessage,
  runtimeDisplayName,
  serverIconUrlFromIcons,
} from "@/app/mcp/mcp-list-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  MCPRegistryServerListResponse,
  MCPRegistryListMetadata,
  MCPRegistryServerResponse,
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";

const PAGE_SIZE = 50;

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function displayHost(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function deliveryTargets(entry: MCPRegistryServerResponse) {
  const targets = [
    ...(entry.server.remotes ?? []).map((remote) => {
      const remoteTarget = remote as Record<string, unknown>;
      const type = stringValue(remoteTarget.type) || "remote";
      const url = stringValue(remoteTarget.url);
      return {
        icon: Network,
        label: runtimeDisplayName(type),
        detail: url ? displayHost(url) : "",
      };
    }),
    ...(entry.server.packages ?? []).map((packageDefinition) => {
      const packageTarget = packageDefinition as Record<string, unknown>;
      const registryType = stringValue(packageTarget.registryType) || "package";
      return {
        icon: Package,
        label: runtimeDisplayName(registryType),
        detail: stringValue(packageTarget.identifier),
      };
    }),
  ];

  const seen = new Set<string>();
  const uniqueTargets = targets.filter((target) => {
    const key = target.label.toLowerCase();
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });

  return uniqueTargets.length > 0
    ? uniqueTargets
    : [{ icon: Package, label: "Unspecified", detail: "" }];
}

function editServerUrl(organizationId: string, serverName: string, version: string) {
  return `/org/${encodeURIComponent(organizationId)}/catalog/edit/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function newServerVersionUrl(organizationId: string, serverName: string, version: string) {
  const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
  const basePath = `/org/${encodeURIComponent(organizationId)}/catalog/new-version/${encodedName}`;
  return `${basePath}?version=${encodeURIComponent(version)}`;
}

function serverVersionUrl(serverName: string, version: string) {
  return `/api/mcp/registry/servers/${[...serverName.split("/"), version]
    .map(encodeURIComponent)
    .join("/")}`;
}

type CatalogListClientProps = {
  initialInstallations: MCPServerInstallationRead[];
  initialMetadata: MCPRegistryListMetadata;
  initialServers: MCPRegistryServerResponse[];
  organizationId: string;
};

export function CatalogListClient({
  initialInstallations,
  initialMetadata,
  initialServers,
  organizationId,
}: CatalogListClientProps) {
  const [installations, setInstallations] =
    useState<MCPServerInstallationRead[]>(initialInstallations);
  const [servers, setServers] = useState<MCPRegistryServerResponse[]>(initialServers);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [currentCursor, setCurrentCursor] = useState("");
  const [nextCursor, setNextCursor] = useState(initialMetadata.nextCursor ?? "");
  const [previousCursors, setPreviousCursors] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const hasInitializedSearch = useRef(false);
  const searchRequestId = useRef(0);

  const installationsByName = useMemo(
    () => {
      const grouped = new Map<string, MCPServerInstallationRead[]>();
      for (const installation of installations) {
        grouped.set(installation.serverName, [
          ...(grouped.get(installation.serverName) ?? []),
          installation,
        ]);
      }
      return grouped;
    },
    [installations]
  );

  const loadServers = useCallback(async ({
    query,
    cursor,
    previous,
  }: {
    query: string;
    cursor: string;
    previous: string[];
  }) => {
    const requestId = searchRequestId.current + 1;
    searchRequestId.current = requestId;
    setIsLoading(true);
    setError("");
    setNotice("");
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), version: "latest" });
    if (query.trim()) {
      params.set("search", query.trim());
    }
    if (cursor) {
      params.set("cursor", cursor);
    }

    try {
      const [serversResponse, installationsResponse] = await Promise.all([
        fetch(`/api/mcp/registry/servers?${params.toString()}`, {
          cache: "no-store",
        }),
        fetch("/api/mcp/registry/installed-servers", {
          cache: "no-store",
        }),
      ]);
      if (!serversResponse.ok || !installationsResponse.ok) {
        throw new Error("Failed to load catalog");
      }
      const serversData = (await serversResponse.json()) as MCPRegistryServerListResponse;
      const installationsData =
        (await installationsResponse.json()) as MCPServerInstallationListResponse;
      if (searchRequestId.current !== requestId) {
        return;
      }
      setServers(serversData.servers);
      setInstallations(installationsData.installations);
      setAppliedSearch(query);
      setCurrentCursor(cursor);
      setNextCursor(serversData.metadata.nextCursor ?? "");
      setPreviousCursors(previous);
    } catch {
      if (searchRequestId.current !== requestId) {
        return;
      }
      setError("Catalog entries could not be loaded.");
    } finally {
      if (searchRequestId.current === requestId) {
        setIsLoading(false);
      }
    }
  }, []);

  async function loadNextPage() {
    if (!nextCursor) {
      return;
    }
    await loadServers({
      query: appliedSearch,
      cursor: nextCursor,
      previous: [...previousCursors, currentCursor],
    });
  }

  async function loadPreviousPage() {
    if (previousCursors.length === 0) {
      return;
    }
    const previous = previousCursors.at(-1) ?? "";
    await loadServers({
      query: appliedSearch,
      cursor: previous,
      previous: previousCursors.slice(0, -1),
    });
  }

  useEffect(() => {
    if (!hasInitializedSearch.current) {
      hasInitializedSearch.current = true;
      return;
    }

    const timeout = window.setTimeout(() => {
      void loadServers({ query: search, cursor: "", previous: [] });
    }, 250);

    return () => window.clearTimeout(timeout);
  }, [loadServers, search]);

  async function deleteServerVersion(serverName: string, version: string) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(serverVersionUrl(serverName, version), {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to delete server."));
      }
      setNotice("Server deleted.");
      await loadServers({
        query: appliedSearch,
        cursor: currentCursor,
        previous: previousCursors,
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The selected server could not be deleted.");
    } finally {
      setIsMutating(false);
    }
  }

  const pageNumber = previousCursors.length + 1;
  const pageStart = servers.length > 0 ? previousCursors.length * PAGE_SIZE + 1 : 0;
  const pageEnd = previousCursors.length * PAGE_SIZE + servers.length;
  const paginationControls = (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3 px-2 text-sm">
      <div className="text-[var(--on-surface-variant)]">
        {servers.length > 0 ? (
          <>
            Showing {pageStart}-{pageEnd}
            {appliedSearch ? ` for "${appliedSearch}"` : ""}
          </>
        ) : (
          "No servers to display"
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button
          disabled={isLoading || previousCursors.length === 0}
          onClick={loadPreviousPage}
          size="sm"
          type="button"
          variant="ghost"
        >
          <ChevronLeft className="size-4" />
          Previous
        </Button>
        <div className="min-w-16 text-center text-sm font-medium text-[var(--on-surface-variant)]">
          Page {pageNumber}
        </div>
        <Button
          disabled={isLoading || !nextCursor}
          onClick={loadNextPage}
          size="sm"
          type="button"
          variant="ghost"
        >
          Next
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );

  return (
    <div>
      <div className="mb-6 rounded-lg border border-[var(--outline-variant)] bg-white p-6">
        <div className="flex flex-col gap-4">
          <Label className="text-[var(--on-surface-variant)]" htmlFor="registry-search">
            Search
          </Label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--outline)]" />
            <Input
              className="h-10 rounded border-[var(--outline-variant)] bg-white pl-9 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20"
              id="registry-search"
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                }
              }}
              placeholder="Name, title, or description"
              type="search"
              value={search}
            />
          </div>
        </div>
      </div>

      <FeedbackMessages error={error} notice={notice} />

      <McpTableCard className="rounded-t-none border-t-0">
          <Table>
            <TableHeader>
              <TableRow className="border-b border-[var(--outline-variant)] bg-[var(--surface-container-low)] hover:bg-[var(--surface-container-low)]">
                <TableHead className="min-w-[360px] bg-transparent px-6 py-4 text-xs font-medium uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
                  Server Name
                </TableHead>
                <TableHead className="w-[260px] bg-transparent px-6 py-4 text-xs font-medium uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
                  Runtime
                </TableHead>
                <TableHead className="w-[150px] bg-transparent px-6 py-4 text-xs font-medium uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
                  Version
                </TableHead>
                <TableHead className="w-[150px] bg-transparent px-6 py-4 text-xs font-medium uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
                  Workspace servers
                </TableHead>
                <TableHead className="w-[180px] bg-transparent px-6 py-4 text-right text-xs font-medium uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {servers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-[var(--on-surface-variant)]">
                    {isLoading
                      ? "Loading catalog entries"
                      : "No supported MCP servers are registered yet"}
                  </TableCell>
                </TableRow>
              ) : (
                servers.map((entry) => {
                  const serverInstallations = installationsByName.get(entry.server.name) ?? [];
                  const updateAvailable = serverInstallations.some(
                    (currentInstallation) => currentInstallation.updateAvailable
                  );
                  const iconUrl = serverIconUrlFromIcons(entry.server.icons);
                  const runtimes = deliveryTargets(entry);
                  return (
                    <TableRow
                      className="border-b border-[var(--outline-variant)] transition-colors hover:bg-[var(--surface-container-low)]"
                      key={`${entry.server.name}:${entry.server.version}`}
                    >
                      <TableCell className="px-6 py-4">
                        <ServerIdentityCell
                          href={`/org/${encodeURIComponent(organizationId)}/catalog`}
                          iconUrl={iconUrl}
                          name={entry.server.name}
                          title={entry.server.title || entry.server.name}
                        />
                      </TableCell>
                      <TableCell className="px-6 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          {runtimes.map((runtime) => {
                            return (
                              <RuntimeBadge
                                detail={runtime.detail}
                                icon={runtime.icon}
                                key={runtime.label}
                                label={runtime.label}
                              />
                            );
                          })}
                          {updateAvailable ? (
                            <Badge className="font-normal" variant="outline">
                              Update available
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="px-6 py-4 text-sm font-medium text-[var(--on-surface)]">
                        {entry.server.version || "-"}
                      </TableCell>
                      <TableCell className="px-6 py-4 text-sm font-medium text-[var(--on-surface)]">
                        {serverInstallations.length > 0 ? serverInstallations.length : "-"}
                      </TableCell>
                      <TableCell className="px-6 py-4 text-right">
                        <div className="flex flex-wrap justify-end gap-2">
                          <Button asChild size="icon" variant="ghost">
                            <Link
                              aria-label={`Add version for ${entry.server.name}`}
                              href={newServerVersionUrl(
                                organizationId,
                                entry.server.name,
                                entry.server.version
                              )}
                              title="Add new version"
                            >
                              <Plus className="size-4" />
                            </Link>
                          </Button>
                          <Button asChild size="icon" variant="ghost">
                            <Link
                              aria-label={`Edit ${entry.server.name}`}
                              href={editServerUrl(
                                organizationId,
                                entry.server.name,
                                entry.server.version
                              )}
                              title="Edit server"
                            >
                              <Pencil className="size-4" />
                            </Link>
                          </Button>
                          <Button
                            aria-label={`Delete ${entry.server.name}`}
                            disabled={isMutating}
                            onClick={() => deleteServerVersion(entry.server.name, entry.server.version)}
                            size="icon"
                            title="Delete server"
                            type="button"
                            variant="ghost"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
      </McpTableCard>

      {paginationControls}
    </div>
  );
}
