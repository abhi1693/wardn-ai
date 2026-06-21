"use client";

import {
  Download,
  KeyRound,
  Network,
  Package,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import type { FormEvent } from "react";
import { useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  MCPRegistryServerResponse,
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";

type InstalledListClientProps = {
  initialInstallations: MCPServerInstallationRead[];
};

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

type InstallTarget = "remote" | "package";

function detailServerUrl(serverName: string, version: string) {
  return `/registry/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function installUrl(serverName: string) {
  return `/api/mcp/registry/installed-servers/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
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
    };
  }

  if (firstPackage) {
    const registryType = stringValue(firstPackage.registryType) || "package";
    const identifier = stringValue(firstPackage.identifier);
    return {
      icon: Package,
      primary: registryType,
      secondary: identifier,
    };
  }

  return {
    icon: Package,
    primary: "Unspecified",
    secondary: "",
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

  return { environmentVariables, headers };
}

function configurationSummary(entry: MCPRegistryServerResponse) {
  const { environmentVariables, headers } = schemaInputs(entry);
  const inputs = [...headers, ...environmentVariables];
  const required = inputs.filter((field) => field.isRequired);
  const secret = inputs.filter((field) => field.isSecret);

  return {
    requiredCount: required.length,
    secretCount: secret.length,
  };
}

function installTargetOptions(entry: MCPRegistryServerResponse) {
  const options: Array<{ value: InstallTarget; label: string }> = [];
  if (entry.server.packages?.length) {
    options.push({ value: "package", label: "Local runtime" });
  }
  if (entry.server.remotes?.length) {
    options.push({ value: "remote", label: "Remote endpoint" });
  }
  return options;
}

function defaultInstallTarget(entry: MCPRegistryServerResponse): InstallTarget {
  return entry.server.packages?.length ? "package" : "remote";
}

function installFields(entry: MCPRegistryServerResponse, target: InstallTarget): InstallField[] {
  const remote = entry.server.remotes?.[0] as Record<string, unknown> | undefined;
  const remoteHeaders = Array.isArray(remote?.headers)
    ? (remote.headers as Record<string, unknown>[])
    : [];
  const packageDefinition = entry.server.packages?.[0] as Record<string, unknown> | undefined;
  const environmentVariables = Array.isArray(packageDefinition?.environmentVariables)
    ? (packageDefinition.environmentVariables as Record<string, unknown>[])
    : [];

  return (target === "remote" ? remoteHeaders : environmentVariables)
    .map((field) => ({
      name: String(field.name ?? ""),
      description: String(field.description ?? ""),
      required: Boolean(field.isRequired),
      secret: Boolean(field.isSecret),
    }))
    .filter((field) => field.name);
}

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

function runtimeLabel(installation: MCPServerInstallationRead) {
  if (installation.installType === "remote") {
    return "Remote endpoint";
  }
  return installation.installType;
}

function statusLabel(status: string) {
  if (status === "enabled") {
    return "Configured";
  }
  return status.replaceAll("_", " ");
}

export function InstalledListClient({
  initialInstallations,
}: InstalledListClientProps) {
  const [installations, setInstallations] =
    useState<MCPServerInstallationRead[]>(initialInstallations);
  const [serverQuery, setServerQuery] = useState("");
  const [serverResults, setServerResults] = useState<MCPRegistryServerResponse[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPRegistryServerResponse | null>(null);
  const [selectedInstallTarget, setSelectedInstallTarget] = useState<InstallTarget>("package");
  const [configName, setConfigName] = useState("default");
  const [installValues, setInstallValues] = useState<Record<string, string>>({});
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>([]);
  const customHeaderId = useRef(0);

  const sortedInstallations = useMemo(
    () =>
      [...installations].sort((left, right) => {
        const serverCompare = left.serverName.localeCompare(right.serverName);
        if (serverCompare !== 0) {
          return serverCompare;
        }
        return left.configName.localeCompare(right.configName);
      }),
    [installations]
  );
  const availableInstallTargets = selectedServer ? installTargetOptions(selectedServer) : [];
  const selectedFields = selectedServer
    ? installFields(selectedServer, selectedInstallTarget)
    : [];

  async function loadInstallations() {
    setIsLoading(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/mcp/registry/installed-servers", {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error("Server configurations could not be loaded.");
      }
      const data = (await response.json()) as MCPServerInstallationListResponse;
      setInstallations(data.installations);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Server configurations could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadServerOptions(query: string) {
    setError("");
    setNotice("");
    setHasSearched(true);

    setIsSearching(true);
    try {
      const params = new URLSearchParams({
        limit: "50",
        version: "latest",
      });
      if (query.trim()) {
        params.set("search", query.trim());
      }
      const response = await fetch(`/api/mcp/registry/servers?${params.toString()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error("Server search failed.");
      }
      const data = (await response.json()) as MCPRegistryServerListResponse;
      setServerResults(data.servers);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Server search failed.");
    } finally {
      setIsSearching(false);
    }
  }

  function openAddDialog() {
    setError("");
    setNotice("");
    setSelectedServer(null);
    setSelectedInstallTarget("package");
    setConfigName("default");
    setInstallValues({});
    setCustomHeaders([]);
    setServerQuery("");
    setServerResults([]);
    setHasSearched(false);
    setDialogOpen(true);
    void loadServerOptions("");
  }

  function selectServerForInstall(server: MCPRegistryServerResponse) {
    const target = defaultInstallTarget(server);
    const existingConfigNames = new Set(
      installations
        .filter((installation) => installation.serverName === server.server.name)
        .map((installation) => installation.configName)
    );
    setSelectedServer(server);
    setSelectedInstallTarget(target);
    setConfigName(existingConfigNames.has("default") ? "" : "default");
    setInstallValues(Object.fromEntries(installFields(server, target).map((field) => [field.name, ""])));
    setCustomHeaders([]);
    setError("");
  }

  function changeInstallTarget(target: InstallTarget) {
    if (!selectedServer) {
      return;
    }
    setSelectedInstallTarget(target);
    setInstallValues(
      Object.fromEntries(installFields(selectedServer, target).map((field) => [field.name, ""]))
    );
    setCustomHeaders([]);
    setError("");
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

  async function submitConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedServer) {
      setError("Select a server first.");
      return;
    }

    const trimmedConfigName = configName.trim();
    if (!trimmedConfigName) {
      setError("Configuration name is required.");
      return;
    }

    const duplicate = installations.some(
      (installation) =>
        installation.serverName === selectedServer.server.name &&
        installation.configName === trimmedConfigName
    );
    if (duplicate) {
      setError("An instance with this name already exists for the selected server.");
      return;
    }

    const missing = selectedFields.filter(
      (field) => field.required && !installValues[field.name]?.trim()
    );
    if (missing.length > 0) {
      setError(`Missing required settings: ${missing.map((field) => field.name).join(", ")}`);
      return;
    }

    const incompleteCustomHeaders =
      selectedInstallTarget === "remote"
        ? customHeaders
            .filter((header) => header.name.trim() || header.value.trim())
            .filter((header) => !header.name.trim() || !header.value.trim())
        : [];
    if (incompleteCustomHeaders.length > 0) {
      setError("Custom headers require both a key and a value.");
      return;
    }

    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(installUrl(selectedServer.server.name), {
        method: "PUT",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          version: "latest",
          configName: trimmedConfigName,
          installTarget: selectedInstallTarget,
          configValues: installPayloadValues(),
        }),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to add configuration."));
      }
      const installation = (await response.json()) as MCPServerInstallationRead;
      setInstallations((current) => [
        ...current.filter((item) => item.id !== installation.id),
        installation,
      ]);
      setDialogOpen(false);
      setConfigName("default");
      setInstallValues({});
      setCustomHeaders([]);
      setNotice("Server instance added.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Server configuration could not be added.");
    } finally {
      setIsMutating(false);
    }
  }

  async function removeInstallation(installation: MCPServerInstallationRead) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        `/api/mcp/registry/installed-server-configs/${encodeURIComponent(installation.id)}`,
        {
          method: "DELETE",
        }
      );
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Failed to remove configuration."));
      }
      setInstallations((current) => current.filter((item) => item.id !== installation.id));
      setNotice("Server instance removed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Server instance could not be removed.");
    } finally {
      setIsMutating(false);
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
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (open || isMutating) {
            return;
          }
          setDialogOpen(false);
          setError("");
        }}
      >
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <form className="space-y-5" onSubmit={submitConfiguration}>
            <DialogHeader>
              <DialogTitle>Install MCP server</DialogTitle>
              <DialogDescription>
                Select a supported server, choose how it should run, then provide the required values.
              </DialogDescription>
            </DialogHeader>

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            {!selectedServer ? (
              <div className="space-y-3">
                <div className="grid gap-2">
                  <Label htmlFor="install-server-search">Server</Label>
                  <div className="flex gap-2">
                    <div className="relative min-w-0 flex-1">
                      <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                      <Input
                        id="install-server-search"
                        onChange={(event) => setServerQuery(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            void loadServerOptions(serverQuery);
                          }
                        }}
                        placeholder="Search supported servers"
                        type="search"
                        value={serverQuery}
                        className="pl-8"
                      />
                    </div>
                    <Button
                      disabled={isSearching}
                      onClick={() => loadServerOptions(serverQuery)}
                      type="button"
                      variant="outline"
                    >
                      <Search className="size-4" />
                      Search
                    </Button>
                  </div>
                </div>

                <div className="max-h-72 overflow-y-auto rounded-md border">
                  {serverResults.length === 0 ? (
                    <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                      {isSearching
                        ? "Loading supported servers"
                        : hasSearched
                          ? "No servers found"
                          : "Loading supported servers"}
                    </div>
                  ) : (
                    serverResults.map((entry) => {
                      const distribution = deliveryDetails(entry);
                      const DistributionIcon = distribution.icon;
                      const config = configurationSummary(entry);

                      return (
                        <button
                          className="flex w-full items-start justify-between gap-3 border-b px-3 py-2 text-left last:border-b-0 hover:bg-muted"
                          key={entry.server.name}
                          onClick={() => selectServerForInstall(entry)}
                          type="button"
                        >
                          <div className="min-w-0">
                            <div className="font-medium">{entry.server.title || entry.server.name}</div>
                            <div className="mt-0.5 break-all text-xs text-muted-foreground">
                              {entry.server.name}
                            </div>
                          </div>
                          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
                            <Badge variant="outline" className="gap-1.5 font-normal capitalize">
                              <DistributionIcon className="size-3.5" />
                              {distribution.primary}
                            </Badge>
                            {config.requiredCount > 0 ? (
                              <Badge variant="outline" className="gap-1.5 font-normal">
                                <KeyRound className="size-3.5" />
                                {config.requiredCount}
                              </Badge>
                            ) : (
                              <Badge variant="outline" className="gap-1.5 font-normal">
                                <ShieldCheck className="size-3.5" />
                                0
                              </Badge>
                            )}
                          </div>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
            ) : null}

            {selectedServer ? (
              <>
                <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/30 p-3">
                  <div className="min-w-0">
                    <div className="font-medium">{selectedServer.server.title || selectedServer.server.name}</div>
                    <div className="mt-0.5 break-all text-xs text-muted-foreground">
                      {selectedServer.server.name}
                    </div>
                  </div>
                  <Button
                    disabled={isMutating}
                    onClick={() => {
                      setSelectedServer(null);
                      setInstallValues({});
                      setCustomHeaders([]);
                      setError("");
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Change
                  </Button>
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="install-config-name">Instance name</Label>
                  <Input
                    autoComplete="off"
                    id="install-config-name"
                    onChange={(event) => setConfigName(event.target.value)}
                    placeholder="home, production, default"
                    value={configName}
                  />
                </div>

                {availableInstallTargets.length > 1 ? (
                  <div className="space-y-2">
                    <Label>Installation target</Label>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {availableInstallTargets.map((option) => {
                        const Icon = option.value === "remote" ? Network : Package;
                        const selected = selectedInstallTarget === option.value;

                        return (
                          <button
                            className={`flex items-start gap-3 rounded-md border p-3 text-left transition-colors hover:bg-muted ${
                              selected ? "border-primary bg-accent" : ""
                            }`}
                            key={option.value}
                            onClick={() => changeInstallTarget(option.value)}
                            type="button"
                          >
                            <Icon className="mt-0.5 size-4 text-muted-foreground" />
                            <div>
                              <div className="text-sm font-medium">
                                {option.value === "remote" ? "Remote endpoint" : "Local runtime"}
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {option.value === "remote"
                                  ? "Connect to an existing MCP endpoint."
                                  : "Run this MCP server from a package or image."}
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                {selectedFields.length > 0 ? (
                  <div className="grid max-h-[45vh] gap-4 overflow-y-auto pr-1">
                    {selectedFields.map((field) => (
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
                    No connection settings are required for this target.
                  </div>
                )}

                {selectedInstallTarget === "remote" ? (
                  <div className="space-y-3 rounded-md border p-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-sm font-medium">Custom headers</div>
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
                ) : null}
              </>
            ) : null}

            <DialogFooter>
              <Button
                disabled={isMutating}
                onClick={() => setDialogOpen(false)}
                type="button"
                variant="outline"
              >
                Cancel
              </Button>
              <Button disabled={isMutating || !selectedServer} type="submit">
                <Download className="size-4" />
                {isMutating ? "Adding" : "Add"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Card>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b p-3">
            <div>
              <div className="text-sm font-medium">Installed configurations</div>
              <div className="text-xs text-muted-foreground">
                {sortedInstallations.length} configured server
                {sortedInstallations.length === 1 ? "" : "s"}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button disabled={isMutating} onClick={openAddDialog} type="button">
                <Plus className="size-4" />
                Add
              </Button>
              <Button disabled={isLoading} onClick={loadInstallations} type="button" variant="outline">
                <RefreshCw className="size-4" />
                Refresh
              </Button>
            </div>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[360px]">Server</TableHead>
                <TableHead className="w-[220px]">Instance</TableHead>
                <TableHead className="w-[170px]">Runtime</TableHead>
                <TableHead className="w-[170px]">Version</TableHead>
                <TableHead className="w-[140px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedInstallations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                    No MCP server configurations have been added yet
                  </TableCell>
                </TableRow>
              ) : (
                sortedInstallations.map((installation) => (
                  <TableRow key={installation.id}>
                    <TableCell>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted">
                          <Package className="size-4 text-muted-foreground" />
                        </div>
                        <div className="min-w-0">
                          <Link
                            className="font-medium text-foreground underline-offset-4 hover:underline"
                            href={detailServerUrl(
                              installation.serverName,
                              installation.installedVersion
                            )}
                          >
                            {installation.server.title || installation.serverName}
                          </Link>
                          <div className="mt-0.5 break-all text-xs text-muted-foreground">
                            {installation.serverName}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1.5">
                        <div className="font-medium">{installation.configName}</div>
                        <Badge variant="success" className="font-normal">
                          {statusLabel(installation.status)}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-normal capitalize">
                        {runtimeLabel(installation)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <div className="text-sm">{installation.installedVersion}</div>
                        {installation.updateAvailable ? (
                          <div className="text-xs text-muted-foreground">
                            Latest: {installation.latestVersion}
                          </div>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <Button
                          disabled={isMutating}
                          onClick={() => removeInstallation(installation)}
                          aria-label={`Delete ${installation.configName}`}
                          size="icon"
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
