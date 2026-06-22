"use client";

import {
  ChevronLeft,
  ChevronRight,
  Network,
  Package,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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

function preferredIcon(entry: MCPRegistryServerResponse) {
  const icon = entry.server.icons?.find((candidate) => {
    const src = (candidate as Record<string, unknown>).src;
    return typeof src === "string" && src.startsWith("https://");
  }) as Record<string, unknown> | undefined;

  return stringValue(icon?.src);
}

function repository(entry: MCPRegistryServerResponse) {
  return entry.server.repository as Record<string, unknown> | null | undefined;
}

function runtimeDisplayName(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === "uvx") {
    return "UVX";
  }
  if (normalized === "npm") {
    return "NPM";
  }
  if (normalized === "pypi") {
    return "PyPI";
  }
  if (normalized === "oci") {
    return "OCI";
  }
  if (normalized === "streamable-http") {
    return "Streamable HTTP";
  }
  if (normalized === "sse") {
    return "SSE";
  }
  return value || "Package";
}

function deliveryDetails(entry: MCPRegistryServerResponse) {
  const firstPackage = entry.server.packages?.[0] as Record<string, unknown> | undefined;
  const firstRemote = entry.server.remotes?.[0] as Record<string, unknown> | undefined;

  if (firstRemote) {
    const type = stringValue(firstRemote.type) || "remote";
    const url = stringValue(firstRemote.url);
    return {
      icon: Network,
      primary: runtimeDisplayName(type),
      secondary: url ? displayHost(url) : "",
      count:
        entry.server.remotes && entry.server.remotes.length > 1
          ? `${entry.server.remotes.length} endpoints`
          : "",
    };
  }

  if (firstPackage) {
    const registryType = stringValue(firstPackage.registryType) || "package";
    const identifier = stringValue(firstPackage.identifier);
    return {
      icon: Package,
      primary: runtimeDisplayName(registryType),
      secondary: identifier,
      count:
        entry.server.packages && entry.server.packages.length > 1
          ? `${entry.server.packages.length} packages`
          : "",
    };
  }

  return {
    icon: Package,
    primary: "Unspecified",
    secondary: "",
    count: "",
  };
}

function detailServerUrl(serverName: string, version: string) {
  return `/registry/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function editServerUrl(serverName: string, version: string) {
  return `/registry/edit/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function installServerUrl(basePath: string, serverName: string, version: string) {
  const params = new URLSearchParams({
    serverName,
    version,
  });
  return `${basePath}/new?${params.toString()}`;
}

function serverVersionUrl(serverName: string, version: string) {
  return `/api/mcp/registry/servers/${[...serverName.split("/"), version]
    .map(encodeURIComponent)
    .join("/")}`;
}

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

type RegistryListClientProps = {
  installBasePath: string;
  initialInstallations: MCPServerInstallationRead[];
  initialMetadata: MCPRegistryListMetadata;
  initialServers: MCPRegistryServerResponse[];
};

export function RegistryListClient({
  installBasePath,
  initialInstallations,
  initialMetadata,
  initialServers,
}: RegistryListClientProps) {
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
  const [selectedUpdates, setSelectedUpdates] = useState<Set<string>>(new Set());

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

  async function loadServers({
    query = appliedSearch,
    cursor = currentCursor,
    previous = previousCursors,
  }: {
    query?: string;
    cursor?: string;
    previous?: string[];
  } = {}) {
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
        throw new Error("Failed to load registry");
      }
      const serversData = (await serversResponse.json()) as MCPRegistryServerListResponse;
      const installationsData =
        (await installationsResponse.json()) as MCPServerInstallationListResponse;
      setServers(serversData.servers);
      setInstallations(installationsData.installations);
      setAppliedSearch(query);
      setCurrentCursor(cursor);
      setNextCursor(serversData.metadata.nextCursor ?? "");
      setPreviousCursors(previous);
    } catch {
      setError("Registry entries could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await loadServers({ query: search, cursor: "", previous: [] });
  }

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

  async function updateSelected() {
    const serverNames = Array.from(selectedUpdates);
    if (serverNames.length === 0) {
      return;
    }

    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/mcp/registry/installed-servers/updates", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({ serverNames }),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to update servers"));
      }
      setSelectedUpdates(new Set());
      setNotice(`${serverNames.length} server${serverNames.length === 1 ? "" : "s"} updated.`);
      await loadServers();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The selected servers could not be updated.");
    } finally {
      setIsMutating(false);
    }
  }

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
      setSelectedUpdates((current) => {
        const next = new Set(current);
        next.delete(serverName);
        return next;
      });
      setNotice("Server deleted.");
      await loadServers();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The selected server could not be deleted.");
    } finally {
      setIsMutating(false);
    }
  }

  function toggleSelected(serverName: string) {
    setSelectedUpdates((current) => {
      const next = new Set(current);
      if (next.has(serverName)) {
        next.delete(serverName);
      } else {
        next.add(serverName);
      }
      return next;
    });
  }

  const pageNumber = previousCursors.length + 1;
  const pageStart = servers.length > 0 ? previousCursors.length * PAGE_SIZE + 1 : 0;
  const pageEnd = previousCursors.length * PAGE_SIZE + servers.length;
  const paginationControls = (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
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
        <div className="min-w-16 text-center text-muted-foreground">Page {pageNumber}</div>
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
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end justify-between gap-3 rounded-md border bg-background p-3"
        onSubmit={handleSearch}
      >
        <div className="grid min-w-72 flex-1 gap-2">
          <Label htmlFor="registry-search">Search</Label>
          <Input
            id="registry-search"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Name, title, or description"
            type="search"
            value={search}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={isLoading} type="submit" variant="outline">
            <Search className="size-4" />
            {isLoading ? "Searching" : "Search"}
          </Button>
          <Button
            disabled={isMutating || selectedUpdates.size === 0}
            onClick={updateSelected}
            type="button"
            variant="outline"
          >
            <RefreshCw className="size-4" />
            Update selected
          </Button>
        </div>
      </form>

      {paginationControls}

      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[44px]"></TableHead>
                <TableHead className="min-w-[360px]">Server</TableHead>
                <TableHead className="w-[230px]">Runtime</TableHead>
                <TableHead className="w-[170px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {servers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-32 text-center text-muted-foreground">
                    {isLoading
                      ? "Loading registry entries"
                      : "No supported MCP servers are registered yet"}
                  </TableCell>
                </TableRow>
              ) : (
                servers.map((entry) => {
                  const serverInstallations = installationsByName.get(entry.server.name) ?? [];
                  const isInstalled = serverInstallations.length > 0;
                  const updateAvailable = serverInstallations.some(
                    (currentInstallation) => currentInstallation.updateAvailable
                  );
                  const iconUrl = preferredIcon(entry);
                  const distribution = deliveryDetails(entry);
                  const DistributionIcon = distribution.icon;
                  return (
                    <TableRow key={`${entry.server.name}:${entry.server.version}`}>
                      <TableCell>
                        <input
                          aria-label={`Select ${entry.server.name} for update`}
                          checked={selectedUpdates.has(entry.server.name)}
                          className="size-4 rounded border-input"
                          disabled={!updateAvailable || isMutating}
                          onChange={() => toggleSelected(entry.server.name)}
                          type="checkbox"
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted">
                            {iconUrl ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                alt=""
                                className="size-full object-contain"
                                referrerPolicy="no-referrer"
                                src={iconUrl}
                              />
                            ) : (
                              <Package className="size-4 text-muted-foreground" />
                            )}
                          </div>
                          <div className="min-w-0 py-0.5">
                            <div className="flex flex-wrap items-center gap-2">
                              <Link
                                className="font-medium text-foreground underline-offset-4 hover:underline"
                                href={detailServerUrl(entry.server.name, entry.server.version)}
                              >
                                {entry.server.title || entry.server.name}
                              </Link>
                              {entry.server.repository ? (
                                <Badge variant="outline" className="font-normal">
                                  {stringValue(repository(entry)?.source) || "source"}
                                </Badge>
                              ) : null}
                            </div>
                            <div className="mt-0.5 break-all text-xs text-muted-foreground">
                              {entry.server.name}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="gap-1.5 font-normal">
                            <DistributionIcon className="size-3.5" />
                            {distribution.primary}
                          </Badge>
                          {isInstalled ? (
                            <Badge variant="outline" className="font-normal">
                              {serverInstallations.length} config
                              {serverInstallations.length === 1 ? "" : "s"}
                            </Badge>
                          ) : null}
                          {updateAvailable ? (
                            <Badge variant="outline" className="font-normal">
                              Update available
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap justify-end gap-2">
                          <Button asChild size="icon" variant="outline">
                            <Link
                              aria-label={`Add installation for ${entry.server.name}`}
                              href={installServerUrl(
                                installBasePath,
                                entry.server.name,
                                entry.server.version
                              )}
                            >
                              <Plus className="size-4" />
                            </Link>
                          </Button>
                          <Button asChild size="icon" variant="outline">
                            <Link
                              aria-label={`Edit ${entry.server.name}`}
                              href={editServerUrl(entry.server.name, entry.server.version)}
                            >
                              <Pencil className="size-4" />
                            </Link>
                          </Button>
                          <Button
                            aria-label={`Delete ${entry.server.name}`}
                            disabled={isMutating}
                            onClick={() => deleteServerVersion(entry.server.name, entry.server.version)}
                            size="icon"
                            type="button"
                            variant="outline"
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
        </CardContent>
      </Card>

      {paginationControls}
    </div>
  );
}
