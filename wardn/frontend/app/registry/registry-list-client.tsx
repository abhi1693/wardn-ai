"use client";

import {
  ChevronLeft,
  ChevronRight,
  Network,
  Package,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  FeedbackMessages,
  McpTableCard,
  RuntimeBadge,
  ServerIdentityCell,
  runtimeDisplayName,
  serverIconUrlFromIcons,
} from "@/app/mcp/mcp-list-ui";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { SearchField } from "@/components/molecules/search-field";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import type {
  MCPRegistryListMetadata,
  MCPRegistryServerResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";
import {
  organizationMcpRegistryDeleteServerVersion,
  organizationMcpRegistryListServers,
} from "@/lib/api/generated/organization-mcp-registry/organization-mcp-registry";

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

type CatalogListClientProps = {
  initialInstallations: MCPServerInstallationRead[];
  initialMetadata: MCPRegistryListMetadata;
  initialServers: MCPRegistryServerResponse[];
  organizationId: string;
  workspaceId: string;
};

export function CatalogListClient({
  initialInstallations,
  initialMetadata,
  initialServers,
  organizationId,
}: CatalogListClientProps) {
  const installations = initialInstallations;
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
  const debouncedSearch = useDebouncedValue(search, 250);
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
    try {
      const serversData = await organizationMcpRegistryListServers(organizationId, {
        limit: PAGE_SIZE,
        version: "latest",
        ...(query.trim() ? { search: query.trim() } : {}),
        ...(cursor ? { cursor } : {}),
      });
      if (searchRequestId.current !== requestId) {
        return;
      }
      setServers(serversData.servers);
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
  }, [organizationId]);

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

    void loadServers({ query: debouncedSearch, cursor: "", previous: [] });
  }, [debouncedSearch, loadServers]);

  async function deleteServerVersion(serverName: string, version: string) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      await organizationMcpRegistryDeleteServerVersion(organizationId, serverName, version);
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
      <div className="text-muted-foreground">
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
        <div className="min-w-16 text-center text-sm font-medium text-muted-foreground">
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
      <div className="mb-4 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <SearchField
          id="registry-search"
          onChange={(event) => setSearch(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
            }
          }}
          placeholder="Name, title, or description"
          value={search}
        />
      </div>

      <FeedbackMessages error={error} notice={notice} />

      <McpTableCard>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[360px]">
                  Server Name
                </TableHead>
                <TableHead className="w-[260px]">
                  Runtime
                </TableHead>
                <TableHead className="w-[150px]">
                  Version
                </TableHead>
                <TableHead className="w-[150px]">
                  Workspace servers
                </TableHead>
                <TableHead className="w-[180px] text-right">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {servers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
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
                      className="transition-colors hover:bg-muted/60"
                      key={`${entry.server.name}:${entry.server.version}`}
                    >
                      <TableCell>
                        <ServerIdentityCell
                          href={`/org/${encodeURIComponent(organizationId)}/catalog`}
                          iconUrl={iconUrl}
                          name={entry.server.name}
                          title={entry.server.title || entry.server.name}
                        />
                      </TableCell>
                      <TableCell>
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
                      <TableCell className="text-sm font-medium">
                        {entry.server.version || "-"}
                      </TableCell>
                      <TableCell className="text-sm font-medium">
                        {serverInstallations.length > 0 ? serverInstallations.length : "-"}
                      </TableCell>
                      <TableCell className="text-right">
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
                          <ConfirmActionDialog
                            actionLabel="Delete version"
                            description="This catalog version will no longer be available for new connections."
                            onConfirm={() => deleteServerVersion(entry.server.name, entry.server.version)}
                            title={`Delete ${entry.server.name} ${entry.server.version}?`}
                            variant="destructive"
                          >
                            <Button
                              aria-label={`Delete ${entry.server.name}`}
                              disabled={isMutating}
                              size="icon"
                              title="Delete server"
                              type="button"
                              variant="ghost"
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </ConfirmActionDialog>
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
