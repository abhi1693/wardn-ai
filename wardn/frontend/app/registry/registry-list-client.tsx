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

function runtimeBadgeClass(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized.includes("http") || normalized.includes("sse")) {
    return "border-sky-200 bg-sky-50 text-sky-700";
  }
  if (normalized === "uvx" || normalized.includes("pypi")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (normalized === "npm") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  if (normalized === "oci") {
    return "border-violet-200 bg-violet-50 text-violet-700";
  }
  if (normalized.includes("remote")) {
    return "border-cyan-200 bg-cyan-50 text-cyan-700";
  }
  return "border-slate-200 bg-slate-100 text-slate-700";
}

function detailServerUrl(organizationId: string, serverName: string, version: string) {
  return `/org/${encodeURIComponent(organizationId)}/registry/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function editServerUrl(organizationId: string, serverName: string, version: string) {
  return `/org/${encodeURIComponent(organizationId)}/registry/edit/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function newServerVersionUrl(organizationId: string, serverName: string, version: string) {
  const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
  const basePath = `/org/${encodeURIComponent(organizationId)}/registry/new-version/${encodedName}`;
  return `${basePath}?version=${encodeURIComponent(version)}`;
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
  initialInstallations: MCPServerInstallationRead[];
  initialMetadata: MCPRegistryListMetadata;
  initialServers: MCPRegistryServerResponse[];
  organizationId: string;
};

export function RegistryListClient({
  initialInstallations,
  initialMetadata,
  initialServers,
  organizationId,
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
      await loadServers();
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
      <form
        className="mb-6 rounded-lg border border-[var(--outline-variant)] bg-white p-6"
        onSubmit={handleSearch}
      >
        <div className="flex flex-col gap-4">
          <Label className="text-[var(--on-surface-variant)]" htmlFor="registry-search">
            Search
          </Label>
          <div className="flex gap-4 max-md:flex-col">
            <Input
              className="h-10 flex-1 rounded border-[var(--outline-variant)] bg-white shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20"
              id="registry-search"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, title, or description"
              type="search"
              value={search}
            />
            <Button className="h-10 px-6" disabled={isLoading} type="submit" variant="outline">
              <Search className="size-4" />
              {isLoading ? "Searching" : "Search"}
            </Button>
          </div>
        </div>
      </form>

      {error ? (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}

      <Card className="overflow-hidden rounded-b-xl rounded-t-none border-[var(--outline-variant)] border-t-0 bg-white shadow-[var(--shadow-card)]">
        <CardContent className="p-0">
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
                  Installations
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
                      ? "Loading registry entries"
                      : "No supported MCP servers are registered yet"}
                  </TableCell>
                </TableRow>
              ) : (
                servers.map((entry) => {
                  const serverInstallations = installationsByName.get(entry.server.name) ?? [];
                  const updateAvailable = serverInstallations.some(
                    (currentInstallation) => currentInstallation.updateAvailable
                  );
                  const iconUrl = preferredIcon(entry);
                  const runtimes = deliveryTargets(entry);
                  return (
                    <TableRow
                      className="border-b border-[var(--outline-variant)] transition-colors hover:bg-[var(--surface-container-low)]"
                      key={`${entry.server.name}:${entry.server.version}`}
                    >
                      <TableCell className="px-6 py-4">
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center overflow-hidden rounded bg-[var(--primary-container)] text-white">
                            {iconUrl ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                alt=""
                                className="size-full object-contain"
                                referrerPolicy="no-referrer"
                                src={iconUrl}
                              />
                            ) : (
                              <Package className="size-4" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <Link
                                className="font-semibold text-primary underline-offset-4 hover:underline"
                                href={detailServerUrl(
                                  organizationId,
                                  entry.server.name,
                                  entry.server.version
                                )}
                              >
                                {entry.server.title || entry.server.name}
                              </Link>
                            </div>
                            <div className="mt-0.5 break-all text-[11px] text-[var(--on-surface-variant)]">
                              {entry.server.name}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="px-6 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          {runtimes.map((runtime) => {
                            const RuntimeIcon = runtime.icon;
                            return (
                              <Badge
                                className={`gap-1.5 rounded px-2 py-1 text-xs font-medium ${runtimeBadgeClass(
                                  runtime.label
                                )}`}
                                key={runtime.label}
                                title={runtime.detail || runtime.label}
                                variant="outline"
                              >
                                <RuntimeIcon className="size-3.5" />
                                {runtime.label}
                              </Badge>
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
        </CardContent>
      </Card>

      {paginationControls}
    </div>
  );
}
