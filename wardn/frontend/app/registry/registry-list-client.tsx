"use client";

import {
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  GitBranch,
  Globe,
  Info,
  KeyRound,
  Plus,
  Network,
  Package,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import type { FormEvent } from "react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

type InstallField = {
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
};

type CustomHeader = {
  id: string;
  name: string;
  value: string;
};

type LinkTarget = {
  label: string;
  url: string;
};

function getOfficialMeta(entry: MCPRegistryServerResponse) {
  return entry._meta["io.modelcontextprotocol.registry/official"];
}

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

function displayDate(value: string | undefined) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
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

function publisherMeta(entry: MCPRegistryServerResponse) {
  const meta = entry.server._meta as Record<string, unknown> | null | undefined;
  return meta?.["io.modelcontextprotocol.registry/publisher-provided"] as
    | Record<string, unknown>
    | undefined;
}

function sourceLinks(entry: MCPRegistryServerResponse): LinkTarget[] {
  const links: LinkTarget[] = [];
  const websiteUrl = entry.server.websiteUrl;
  const repoUrl = stringValue(repository(entry)?.url);
  const publisher = publisherMeta(entry);
  const docsUrl = stringValue(publisher?.docs);
  const connectUrl = stringValue(publisher?.connect);

  if (websiteUrl) {
    links.push({ label: "Website", url: websiteUrl });
  }
  if (repoUrl && repoUrl !== websiteUrl) {
    links.push({ label: "Repository", url: repoUrl });
  }
  if (docsUrl && docsUrl !== websiteUrl && docsUrl !== repoUrl) {
    links.push({ label: "Docs", url: docsUrl });
  }
  if (connectUrl && connectUrl !== websiteUrl && connectUrl !== repoUrl && connectUrl !== docsUrl) {
    links.push({ label: "Connect", url: connectUrl });
  }

  return links.slice(0, 3);
}

function deliveryDetails(entry: MCPRegistryServerResponse) {
  const firstPackage = entry.server.packages?.[0] as Record<string, unknown> | undefined;
  const firstRemote = entry.server.remotes?.[0] as Record<string, unknown> | undefined;

  if (firstRemote) {
    const type = stringValue(firstRemote.type) || "remote";
    const url = stringValue(firstRemote.url);
    return {
      icon: Network,
      primary: type,
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
      primary: registryType,
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

function schemaInputs(entry: MCPRegistryServerResponse) {
  const headers = (entry.server.remotes ?? []).flatMap((remote) => {
    const value = (remote as Record<string, unknown>).headers;
    return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  });
  const environmentVariables = (entry.server.packages ?? []).flatMap((packageDefinition) => {
    const value = (packageDefinition as Record<string, unknown>).environmentVariables;
    return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  });
  const packageArguments = (entry.server.packages ?? []).flatMap((packageDefinition) => {
    const value = (packageDefinition as Record<string, unknown>).packageArguments;
    return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  });

  return { environmentVariables, headers, packageArguments };
}

function configurationSummary(entry: MCPRegistryServerResponse) {
  const { environmentVariables, headers, packageArguments } = schemaInputs(entry);
  const inputs = [...headers, ...environmentVariables, ...packageArguments];
  const required = inputs.filter((field) => field.isRequired);
  const secret = inputs.filter((field) => field.isSecret);
  const requiredNames = required
    .map((field) => stringValue(field.name) || stringValue(field.type))
    .filter(Boolean)
    .slice(0, 3);

  return {
    requiredCount: required.length,
    secretCount: secret.length,
    requiredNames,
    totalCount: inputs.length,
  };
}

function installUrl(serverName: string) {
  return `/api/mcp/registry/installed-servers/${serverName
    .split("/")
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

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

function installFields(entry: MCPRegistryServerResponse): InstallField[] {
  const remote = entry.server.remotes?.[0] as Record<string, unknown> | undefined;
  const remoteHeaders = Array.isArray(remote?.headers)
    ? (remote.headers as Record<string, unknown>[])
    : [];
  const packageDefinition = entry.server.packages?.[0] as Record<string, unknown> | undefined;
  const environmentVariables = Array.isArray(packageDefinition?.environmentVariables)
    ? (packageDefinition.environmentVariables as Record<string, unknown>[])
    : [];

  const fields = [...remoteHeaders, ...environmentVariables]
    .map((field) => ({
      name: String(field.name ?? ""),
      description: String(field.description ?? ""),
      required: Boolean(field.isRequired),
      secret: Boolean(field.isSecret),
    }))
    .filter((field) => field.name);

  return fields;
}

type RegistryListClientProps = {
  initialInstallations: MCPServerInstallationRead[];
  initialMetadata: MCPRegistryListMetadata;
  initialServers: MCPRegistryServerResponse[];
};

export function RegistryListClient({
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
  const [installTarget, setInstallTarget] = useState<MCPRegistryServerResponse | null>(null);
  const [detailsTarget, setDetailsTarget] = useState<MCPRegistryServerResponse | null>(null);
  const [installValues, setInstallValues] = useState<Record<string, string>>({});
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>([]);
  const customHeaderId = useRef(0);

  const installationsByName = useMemo(
    () => new Map(installations.map((installation) => [installation.serverName, installation])),
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

  async function installLatest(serverName: string, configValues: Record<string, string> = {}) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(installUrl(serverName), {
        method: "PUT",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({ version: "latest", configValues }),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to install server"));
      }
      setNotice("Server installed.");
      setInstallTarget(null);
      setInstallValues({});
      await loadServers();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The selected server could not be installed.");
    } finally {
      setIsMutating(false);
    }
  }

  function beginInstall(entry: MCPRegistryServerResponse) {
    const fields = installFields(entry);
    setError("");
    setNotice("");
    setInstallValues(
      Object.fromEntries(fields.map((field) => [field.name, installValues[field.name] ?? ""]))
    );
    setCustomHeaders([]);
    setInstallTarget(entry);
  }

  function addCustomHeader() {
    customHeaderId.current += 1;
    setCustomHeaders((current) => [
      ...current,
      {
        id: `custom-header-${customHeaderId.current}`,
        name: "",
        value: "",
      },
    ]);
  }

  function updateCustomHeader(id: string, patch: Partial<CustomHeader>) {
    setCustomHeaders((current) =>
      current.map((header) => (header.id === id ? { ...header, ...patch } : header))
    );
  }

  function removeCustomHeader(id: string) {
    setCustomHeaders((current) => current.filter((header) => header.id !== id));
  }

  function installPayloadValues() {
    const payload = { ...installValues };
    for (const header of customHeaders) {
      const name = header.name.trim();
      const value = header.value.trim();
      if (name && value) {
        payload[`headers.${name}`] = value;
      }
    }
    return payload;
  }

  async function submitConfiguredInstall(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!installTarget) {
      return;
    }

    const missing = installFields(installTarget).filter(
      (field) => field.required && !installValues[field.name]?.trim()
    );
    if (missing.length > 0) {
      setError(`Missing required connection settings: ${missing.map((field) => field.name).join(", ")}`);
      return;
    }

    const incompleteCustomHeaders = customHeaders.filter(
      (header) => header.name.trim() || header.value.trim()
    ).filter((header) => !header.name.trim() || !header.value.trim());
    if (incompleteCustomHeaders.length > 0) {
      setError("Custom headers require both a key and a value.");
      return;
    }

    await installLatest(installTarget.server.name, installPayloadValues());
  }

  async function uninstallServer(serverName: string) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(installUrl(serverName), {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to uninstall server"));
      }
      setSelectedUpdates((current) => {
        const next = new Set(current);
        next.delete(serverName);
        return next;
      });
      setNotice("Server uninstalled.");
      await loadServers();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The selected server could not be uninstalled.");
    } finally {
      setIsMutating(false);
    }
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

  const installTargetFields = installTarget ? installFields(installTarget) : [];
  const detailsDistribution = detailsTarget ? deliveryDetails(detailsTarget) : null;
  const detailsConfig = detailsTarget ? configurationSummary(detailsTarget) : null;
  const detailsInputs = detailsTarget ? schemaInputs(detailsTarget) : null;
  const detailsLinks = detailsTarget ? sourceLinks(detailsTarget) : [];
  const detailsMeta = detailsTarget ? getOfficialMeta(detailsTarget) : null;
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

      <Dialog
        open={Boolean(detailsTarget)}
        onOpenChange={(open) => {
          if (!open) {
            setDetailsTarget(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          {detailsTarget && detailsDistribution && detailsConfig && detailsInputs && detailsMeta ? (
            <div className="space-y-5">
              <DialogHeader>
                <DialogTitle>{detailsTarget.server.title || detailsTarget.server.name}</DialogTitle>
                <DialogDescription className="break-all">
                  {detailsTarget.server.name}
                </DialogDescription>
              </DialogHeader>

              <div className="text-sm leading-6 text-muted-foreground">
                {detailsTarget.server.description}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-3 rounded-md border p-3">
                  <div className="text-sm font-medium">Distribution</div>
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center gap-2">
                      <detailsDistribution.icon className="size-4 text-muted-foreground" />
                      <span className="capitalize">{detailsDistribution.primary}</span>
                    </div>
                    {detailsDistribution.secondary ? (
                      <div className="break-all text-muted-foreground">
                        {detailsDistribution.secondary}
                      </div>
                    ) : null}
                    {detailsTarget.server.remotes?.length ? (
                      <div className="space-y-1">
                        <div className="text-xs font-medium text-muted-foreground">Remote endpoints</div>
                        {detailsTarget.server.remotes.map((remote, index) => {
                          const value = remote as Record<string, unknown>;
                          return (
                            <div className="break-all text-xs text-muted-foreground" key={`${detailsTarget.server.name}-remote-${index}`}>
                              {stringValue(value.type) || "remote"} · {stringValue(value.url)}
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                    {detailsTarget.server.packages?.length ? (
                      <div className="space-y-1">
                        <div className="text-xs font-medium text-muted-foreground">Packages</div>
                        {detailsTarget.server.packages.map((packageDefinition, index) => {
                          const value = packageDefinition as Record<string, unknown>;
                          return (
                            <div className="break-all text-xs text-muted-foreground" key={`${detailsTarget.server.name}-package-${index}`}>
                              {stringValue(value.registryType) || "package"} · {stringValue(value.identifier)}
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="space-y-3 rounded-md border p-3">
                  <div className="text-sm font-medium">Configuration</div>
                  <div className="space-y-2 text-sm">
                    <div>
                      {detailsConfig.requiredCount > 0
                        ? `${detailsConfig.requiredCount} required input${detailsConfig.requiredCount === 1 ? "" : "s"}`
                        : "No required inputs"}
                    </div>
                    {detailsConfig.secretCount > 0 ? (
                      <div className="text-muted-foreground">
                        {detailsConfig.secretCount} secret value
                        {detailsConfig.secretCount === 1 ? "" : "s"}
                      </div>
                    ) : null}
                    {[...detailsInputs.headers, ...detailsInputs.environmentVariables, ...detailsInputs.packageArguments].length ? (
                      <div className="space-y-1">
                        {[...detailsInputs.headers, ...detailsInputs.environmentVariables, ...detailsInputs.packageArguments]
                          .slice(0, 8)
                          .map((field, index) => (
                            <div
                              className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground"
                              key={`${detailsTarget.server.name}-input-${index}`}
                            >
                              <span className="font-medium text-foreground">
                                {stringValue(field.name) || stringValue(field.type) || "Input"}
                              </span>
                              {field.isRequired ? <Badge variant="outline">Required</Badge> : null}
                              {field.isSecret ? <Badge variant="outline">Secret</Badge> : null}
                            </div>
                          ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-3 rounded-md border p-3">
                  <div className="text-sm font-medium">Source</div>
                  {detailsLinks.length > 0 ? (
                    <div className="space-y-2">
                      {detailsLinks.map((link) => (
                        <a
                          className="flex items-center gap-2 text-sm text-primary hover:underline"
                          href={link.url}
                          key={`${detailsTarget.server.name}-${link.label}`}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {link.label === "Repository" ? (
                            <GitBranch className="size-4" />
                          ) : link.label === "Website" ? (
                            <Globe className="size-4" />
                          ) : (
                            <ExternalLink className="size-4" />
                          )}
                          <span>{link.label}</span>
                        </a>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">No source links provided.</div>
                  )}
                </div>

                <div className="space-y-3 rounded-md border p-3">
                  <div className="text-sm font-medium">Registry</div>
                  <div className="space-y-1 text-sm">
                    <div>Version {detailsTarget.server.version}</div>
                    <div className="capitalize text-muted-foreground">
                      {detailsMeta.status}
                    </div>
                    {displayDate(detailsMeta.publishedAt) ? (
                      <div className="text-muted-foreground">
                        Published {displayDate(detailsMeta.publishedAt)}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>

              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setDetailsTarget(null)}>
                  Close
                </Button>
                <Button
                  disabled={isMutating || Boolean(installationsByName.get(detailsTarget.server.name))}
                  onClick={() => {
                    setDetailsTarget(null);
                    beginInstall(detailsTarget);
                  }}
                  type="button"
                >
                  <Download className="size-4" />
                  Install
                </Button>
              </DialogFooter>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(installTarget)}
        onOpenChange={(open) => {
          if (open || isMutating) {
            return;
          }
          setInstallTarget(null);
          setInstallValues({});
          setCustomHeaders([]);
        }}
      >
        <DialogContent>
          {installTarget ? (
            <form className="space-y-5" onSubmit={submitConfiguredInstall}>
              <DialogHeader>
                <DialogTitle>
                  Install {installTarget.server.title || installTarget.server.name}
                </DialogTitle>
                <DialogDescription className="break-all">
                  {installTarget.server.name}
                </DialogDescription>
              </DialogHeader>

              {installTargetFields.length > 0 ? (
                <div className="grid max-h-[55vh] gap-4 overflow-y-auto pr-1">
                  {installTargetFields.map((field) => (
                    <div className="grid gap-2" key={field.name}>
                      <Label htmlFor={`install-${field.name}`}>
                        {field.name}
                        {field.required ? <span className="text-red-600"> *</span> : null}
                      </Label>
                      <Input
                        autoComplete="off"
                        id={`install-${field.name}`}
                        onChange={(event) =>
                          setInstallValues((current) => ({
                            ...current,
                            [field.name]: event.target.value,
                          }))
                        }
                        placeholder={field.secret ? "Secret value" : "Value"}
                        type={field.secret ? "password" : "text"}
                        value={installValues[field.name] ?? ""}
                      />
                      {field.description ? (
                        <div className="text-xs leading-5 text-muted-foreground">
                          {field.description}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                  No connection settings are required for this server.
                </div>
              )}

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">Custom headers</div>
                    <div className="text-xs text-muted-foreground">
                      Add only the headers this server requires.
                    </div>
                  </div>
                  <Button
                    disabled={isMutating}
                    onClick={addCustomHeader}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Plus className="size-4" />
                    Add header
                  </Button>
                </div>

                {customHeaders.length > 0 ? (
                  <div className="space-y-2">
                    {customHeaders.map((header) => (
                      <div
                        className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
                        key={header.id}
                      >
                        <Input
                          autoComplete="off"
                          onChange={(event) =>
                            updateCustomHeader(header.id, { name: event.target.value })
                          }
                          placeholder="Header key"
                          value={header.name}
                        />
                        <Input
                          autoComplete="off"
                          onChange={(event) =>
                            updateCustomHeader(header.id, { value: event.target.value })
                          }
                          placeholder="Header value"
                          type="password"
                          value={header.value}
                        />
                        <Button
                          aria-label="Remove custom header"
                          disabled={isMutating}
                          onClick={() => removeCustomHeader(header.id)}
                          size="icon"
                          type="button"
                          variant="outline"
                        >
                          <X className="size-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>

              <DialogFooter>
                <Button
                  disabled={isMutating}
                  onClick={() => {
                    setInstallTarget(null);
                    setInstallValues({});
                    setCustomHeaders([]);
                  }}
                  type="button"
                  variant="outline"
                >
                  Cancel
                </Button>
                <Button disabled={isMutating} type="submit">
                  <Download className="size-4" />
                  {isMutating ? "Installing" : "Install"}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[44px]"></TableHead>
                <TableHead className="min-w-[420px]">Server</TableHead>
                <TableHead className="w-[230px]">Runtime</TableHead>
                <TableHead className="w-[150px]">Installation</TableHead>
                <TableHead className="w-[220px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {servers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                    {isLoading
                      ? "Loading registry entries"
                      : "No supported MCP servers are registered yet"}
                  </TableCell>
                </TableRow>
              ) : (
                servers.map((entry) => {
                  const installation = installationsByName.get(entry.server.name);
                  const isInstalled = Boolean(installation);
                  const updateAvailable = Boolean(installation?.updateAvailable);
                  const iconUrl = preferredIcon(entry);
                  const distribution = deliveryDetails(entry);
                  const DistributionIcon = distribution.icon;
                  const config = configurationSummary(entry);
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
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="font-medium">{entry.server.title || entry.server.name}</div>
                              {entry.server.repository ? (
                                <Badge variant="outline" className="font-normal">
                                  {stringValue(repository(entry)?.source) || "source"}
                                </Badge>
                              ) : null}
                            </div>
                            <div className="mt-0.5 break-all text-xs text-muted-foreground">
                              {entry.server.name}
                            </div>
                            <div className="mt-1 max-w-3xl text-sm leading-5 text-muted-foreground line-clamp-2">
                              {entry.server.description}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="gap-1.5 font-normal capitalize">
                            <DistributionIcon className="size-3.5" />
                            {distribution.primary}
                          </Badge>
                          {config.requiredCount > 0 ? (
                            <Badge variant="outline" className="gap-1.5 font-normal">
                              <KeyRound className="size-3.5" />
                              {config.requiredCount} required
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="gap-1.5 font-normal">
                              <ShieldCheck className="size-3.5" />
                              No required inputs
                            </Badge>
                          )}
                          {config.secretCount > 0 ? (
                            <Badge variant="outline" className="font-normal">
                              {config.secretCount} secret
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="space-y-1.5">
                          <Badge variant={isInstalled ? "success" : "outline"} className="font-normal">
                            {isInstalled ? statusLabel(installation?.status ?? "installed") : "Not installed"}
                          </Badge>
                          {installation ? (
                            <div className="text-xs text-muted-foreground">
                              {installation.installedVersion}
                            </div>
                          ) : null}
                          {updateAvailable ? (
                            <div className="text-xs text-muted-foreground">Update available</div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap justify-end gap-2">
                          <Button
                            disabled={isMutating}
                            onClick={() => setDetailsTarget(entry)}
                            size="sm"
                            type="button"
                            variant="outline"
                          >
                            <Info className="size-4" />
                            Details
                          </Button>
                          {isInstalled ? (
                            <Button
                              disabled={isMutating}
                              onClick={() => uninstallServer(entry.server.name)}
                              size="sm"
                              type="button"
                              variant="outline"
                            >
                              <Trash2 className="size-4" />
                              Uninstall
                            </Button>
                          ) : (
                            <Button
                              disabled={isMutating}
                              onClick={() => beginInstall(entry)}
                              size="sm"
                              type="button"
                              variant="outline"
                            >
                              <Download className="size-4" />
                              Install
                            </Button>
                          )}
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
