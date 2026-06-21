"use client";

import { Download, KeyRound, Network, Package, Search, ShieldCheck, X } from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type {
  MCPRegistryServerListResponse,
  MCPRegistryServerResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";

type InstallTarget = "remote" | "package";

type InstallField = {
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
  format: string;
  defaultValue: string;
  options: string[];
  section: "connection" | "runtime";
};

type CustomHeader = {
  id: string;
  name: string;
  value: string;
};

type InstallFormClientProps = {
  initialInstallation?: MCPServerInstallationRead | null;
  initialInstallations: MCPServerInstallationRead[];
  initialServers?: MCPRegistryServerResponse[];
};

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
    return { icon: Network, primary: type, secondary: url ? displayHost(url) : "" };
  }
  if (firstPackage) {
    const registryType = stringValue(firstPackage.registryType) || "package";
    return { icon: Package, primary: registryType, secondary: stringValue(firstPackage.identifier) };
  }
  return { icon: Package, primary: "Unspecified", secondary: "" };
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

function installTargetFromInstallation(installation: MCPServerInstallationRead): InstallTarget {
  return installation.installType === "remote" ? "remote" : "package";
}

function serverResponseFromInstallation(installation: MCPServerInstallationRead): MCPRegistryServerResponse {
  return {
    server: installation.server,
    _meta: {
      "io.modelcontextprotocol.registry/official": {
        status: "active",
        statusChangedAt: installation.updatedAt,
        publishedAt: installation.installedAt,
        updatedAt: installation.updatedAt,
        isLatest: !installation.updateAvailable,
      },
    },
  } as MCPRegistryServerResponse;
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
  const inputs = [...headers, ...environmentVariables, ...packageArguments.filter((field) => field.name)];
  return {
    requiredCount: inputs.filter((field) => field.isRequired).length,
    secretCount: inputs.filter((field) => field.isSecret).length,
  };
}

function installFields(entry: MCPRegistryServerResponse, target: InstallTarget): InstallField[] {
  const remote = entry.server.remotes?.[0] as Record<string, unknown> | undefined;
  const remoteHeaders = Array.isArray(remote?.headers) ? (remote.headers as Record<string, unknown>[]) : [];
  const packageDefinition = entry.server.packages?.[0] as Record<string, unknown> | undefined;
  const environmentVariables = Array.isArray(packageDefinition?.environmentVariables)
    ? (packageDefinition.environmentVariables as Record<string, unknown>[])
    : [];
  const packageArguments = Array.isArray(packageDefinition?.packageArguments)
    ? (packageDefinition.packageArguments as Record<string, unknown>[])
    : [];

  const connectionFields = (target === "remote" ? remoteHeaders : environmentVariables).map((field) => ({
    name: String(field.name ?? ""),
    description: String(field.description ?? ""),
    required: Boolean(field.isRequired),
    secret: Boolean(field.isSecret),
    format: String(field.format ?? "string"),
    defaultValue: String(field.default ?? ""),
    options: Array.isArray(field.options) ? field.options.map(String) : [],
    section: "connection" as const,
  }));
  const runtimeFields = target === "package"
    ? packageArguments.map((field) => ({
        name: String(field.name ?? ""),
        description: String(field.description ?? ""),
        required: Boolean(field.isRequired),
        secret: Boolean(field.isSecret),
        format: String(field.format ?? "string"),
        defaultValue: String(field.default ?? ""),
        options: Array.isArray(field.options) ? field.options.map(String) : [],
        section: "runtime" as const,
      }))
    : [];

  return [...connectionFields, ...runtimeFields].filter((field) => field.name);
}

function defaultInstallValues(fields: InstallField[]) {
  return Object.fromEntries(fields.map((field) => [field.name, field.defaultValue]));
}

function configuredFieldValues(fields: InstallField[], installation: MCPServerInstallationRead) {
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const configuredValues = installation.configuredValues ?? {};
  const packageConfig = runtimeConfig.package as Record<string, unknown> | undefined;
  const transportConfig = runtimeConfig.transport as Record<string, unknown> | undefined;
  const configuredInputs = [
    ...((packageConfig?.environmentVariables as Record<string, unknown>[] | undefined) ?? []),
    ...((packageConfig?.packageArguments as Record<string, unknown>[] | undefined) ?? []),
    ...((transportConfig?.headers as Record<string, unknown>[] | undefined) ?? []),
  ];

  return Object.fromEntries(fields.map((field) => {
    const configured = configuredInputs.find((item) => item.name === field.name);
    if (configuredValues[field.name] !== undefined) {
      return [field.name, configuredValues[field.name]];
    }
    if (field.format === "boolean" && configured?.configured) {
      return [field.name, "true"];
    }
    return [field.name, field.defaultValue];
  }));
}

function configuredFieldNames(installation: MCPServerInstallationRead | null) {
  if (!installation) {
    return new Set<string>();
  }
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const packageConfig = runtimeConfig.package as Record<string, unknown> | undefined;
  const transportConfig = runtimeConfig.transport as Record<string, unknown> | undefined;
  const configuredInputs = [
    ...((packageConfig?.environmentVariables as Record<string, unknown>[] | undefined) ?? []),
    ...((packageConfig?.packageArguments as Record<string, unknown>[] | undefined) ?? []),
    ...((transportConfig?.headers as Record<string, unknown>[] | undefined) ?? []),
  ];
  return new Set(configuredInputs
    .filter((item) => item.configured && typeof item.name === "string")
    .map((item) => String(item.name)));
}

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

function InstallFieldControl({
  field,
  hasExistingValue = false,
  onChange,
  value,
}: {
  field: InstallField;
  hasExistingValue?: boolean;
  onChange: (value: string) => void;
  value: string;
}) {
  const inputId = `install-${field.name}`;

  if (field.format === "boolean") {
    return (
      <label className="flex items-start gap-3 rounded-md border p-3 text-sm">
        <input
          checked={value === "true"}
          className="mt-1"
          onChange={(event) => onChange(event.target.checked ? "true" : "false")}
          type="checkbox"
        />
        <span className="grid gap-1">
          <span className="font-medium">
            {field.name}
            {field.required ? <span className="text-red-600"> *</span> : null}
          </span>
          {field.description ? <span className="text-xs leading-5 text-muted-foreground">{field.description}</span> : null}
        </span>
      </label>
    );
  }

  return (
    <div className="grid gap-2">
      <Label htmlFor={inputId}>
        {field.name}
        {field.required ? <span className="text-red-600"> *</span> : null}
      </Label>
      {field.options.length > 0 || field.format === "select" ? (
        <Select onValueChange={onChange} value={value}>
          <SelectTrigger id={inputId}>
            <SelectValue placeholder="Default" />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((option) => (
              <SelectItem key={option} value={option}>{option}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          autoComplete="off"
          id={inputId}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.secret && hasExistingValue ? "Configured value" : field.secret ? "Secret value" : "Value"}
          type={field.secret ? "password" : field.format === "integer" ? "number" : "text"}
          value={value}
        />
      )}
      {field.description ? <div className="text-xs leading-5 text-muted-foreground">{field.description}</div> : null}
    </div>
  );
}

export function InstallFormClient({
  initialInstallation = null,
  initialInstallations,
  initialServers = [],
}: InstallFormClientProps) {
  const router = useRouter();
  const isEdit = Boolean(initialInstallation);
  const [installations, setInstallations] = useState<MCPServerInstallationRead[]>(initialInstallations);
  const [serverQuery, setServerQuery] = useState("");
  const [serverResults, setServerResults] = useState<MCPRegistryServerResponse[]>(initialServers);
  const [hasSearched, setHasSearched] = useState(initialServers.length > 0);
  const [isSearching, setIsSearching] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");
  const [selectedServer, setSelectedServer] = useState<MCPRegistryServerResponse | null>(() =>
    initialInstallation ? serverResponseFromInstallation(initialInstallation) : null
  );
  const [selectedInstallTarget, setSelectedInstallTarget] = useState<InstallTarget>(() =>
    initialInstallation ? installTargetFromInstallation(initialInstallation) : "package"
  );
  const initialFields = initialInstallation && selectedServer
    ? installFields(selectedServer, installTargetFromInstallation(initialInstallation))
    : [];
  const [configName, setConfigName] = useState(initialInstallation?.configName ?? "default");
  const [installValues, setInstallValues] = useState<Record<string, string>>(() =>
    initialInstallation ? configuredFieldValues(initialFields, initialInstallation) : {}
  );
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>([]);
  const customHeaderId = useRef(0);

  const availableInstallTargets = selectedServer ? installTargetOptions(selectedServer) : [];
  const selectedFields = selectedServer ? installFields(selectedServer, selectedInstallTarget) : [];
  const connectionFields = selectedFields.filter((field) => field.section === "connection");
  const runtimeFields = selectedFields.filter((field) => field.section === "runtime");
  const existingConfiguredFields = useMemo(() => configuredFieldNames(initialInstallation), [initialInstallation]);

  async function loadServerOptions(query: string) {
    setError("");
    setHasSearched(true);
    setIsSearching(true);
    try {
      const params = new URLSearchParams({ limit: "50", version: "latest" });
      if (query.trim()) {
        params.set("search", query.trim());
      }
      const response = await fetch(`/api/mcp/registry/servers?${params.toString()}`, { cache: "no-store" });
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
    setInstallValues(defaultInstallValues(installFields(server, target)));
    setCustomHeaders([]);
    setError("");
  }

  function changeInstallTarget(target: InstallTarget) {
    if (!selectedServer || isEdit) {
      return;
    }
    setSelectedInstallTarget(target);
    setInstallValues(defaultInstallValues(installFields(selectedServer, target)));
    setCustomHeaders([]);
    setError("");
  }

  function addCustomHeader() {
    customHeaderId.current += 1;
    setCustomHeaders((current) => [...current, { id: `custom-header-${customHeaderId.current}`, name: "", value: "" }]);
  }

  function updateCustomHeader(id: string, patch: Partial<CustomHeader>) {
    setCustomHeaders((current) => current.map((header) => (header.id === id ? { ...header, ...patch } : header)));
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
      setError("Instance name is required.");
      return;
    }

    const duplicate = installations.some(
      (installation) =>
        installation.id !== initialInstallation?.id &&
        installation.serverName === selectedServer.server.name &&
        installation.configName === trimmedConfigName
    );
    if (duplicate) {
      setError("An instance with this name already exists for the selected server.");
      return;
    }

    const missing = selectedFields.filter((field) => field.required && !isEdit && !installValues[field.name]?.trim());
    if (missing.length > 0) {
      setError(`Missing required settings: ${missing.map((field) => field.name).join(", ")}`);
      return;
    }

    const incompleteCustomHeaders = customHeaders
      .filter((header) => header.name.trim() || header.value.trim())
      .filter((header) => !header.name.trim() || !header.value.trim());
    if (incompleteCustomHeaders.length > 0) {
      setError("Custom headers require both a key and a value.");
      return;
    }

    setIsMutating(true);
    setError("");
    try {
      const response = await fetch(installUrl(selectedServer.server.name), {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          version: initialInstallation?.installedVersion ?? "latest",
          configName: trimmedConfigName,
          installTarget: selectedInstallTarget,
          configValues: installPayloadValues(),
        }),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, isEdit ? "Failed to save instance." : "Failed to add instance."));
      }
      const installation = (await response.json()) as MCPServerInstallationRead;
      setInstallations((current) => [...current.filter((item) => item.id !== installation.id), installation]);
      router.push("/install");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Server instance could not be saved.");
    } finally {
      setIsMutating(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={submitConfiguration}>
      {error ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

      {!selectedServer ? (
        <Card>
          <CardHeader><CardTitle>Server</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2">
              <Label htmlFor="install-server-search">Server</Label>
              <div className="flex gap-2">
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                  <Input
                    className="pl-8"
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
                  />
                </div>
                <Button disabled={isSearching} onClick={() => loadServerOptions(serverQuery)} type="button" variant="outline">
                  <Search className="size-4" />
                  Search
                </Button>
              </div>
            </div>
            <div className="rounded-md border">
              {serverResults.length === 0 ? (
                <div className="px-3 py-10 text-center text-sm text-muted-foreground">
                  {isSearching ? "Loading supported servers" : hasSearched ? "No servers found" : "No supported MCP servers are registered yet"}
                </div>
              ) : (
                serverResults.map((entry) => {
                  const distribution = deliveryDetails(entry);
                  const DistributionIcon = distribution.icon;
                  const config = configurationSummary(entry);
                  return (
                    <button
                      className="flex w-full items-start justify-between gap-3 border-b px-3 py-3 text-left last:border-b-0 hover:bg-muted"
                      key={entry.server.name}
                      onClick={() => selectServerForInstall(entry)}
                      type="button"
                    >
                      <div className="min-w-0">
                        <div className="font-medium">{entry.server.title || entry.server.name}</div>
                        <div className="mt-0.5 break-all text-xs text-muted-foreground">{entry.server.name}</div>
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
          </CardContent>
        </Card>
      ) : null}

      {selectedServer ? (
        <>
          <Card>
            <CardHeader><CardTitle>Server</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/30 p-3">
                <div className="min-w-0">
                  <div className="font-medium">{selectedServer.server.title || selectedServer.server.name}</div>
                  <div className="mt-0.5 break-all text-xs text-muted-foreground">{selectedServer.server.name}</div>
                </div>
                {!isEdit ? (
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
                ) : null}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="install-config-name">Instance name</Label>
                  <Input
                    autoComplete="off"
                    disabled={isEdit}
                    id="install-config-name"
                    onChange={(event) => setConfigName(event.target.value)}
                    placeholder="home, production, default"
                    value={configName}
                  />
                </div>
                {isEdit ? (
                  <div className="grid gap-2">
                    <Label>Installation target</Label>
                    <div className="flex min-h-9 items-center gap-2 rounded-md border bg-muted/30 px-3 text-sm">
                      {selectedInstallTarget === "remote" ? <Network className="size-4 text-muted-foreground" /> : <Package className="size-4 text-muted-foreground" />}
                      {selectedInstallTarget === "remote" ? "Remote endpoint" : "Local runtime"}
                    </div>
                  </div>
                ) : availableInstallTargets.length > 1 ? (
                  <div className="grid gap-2 md:col-span-2">
                    <Label>Installation target</Label>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {availableInstallTargets.map((option) => {
                        const Icon = option.value === "remote" ? Network : Package;
                        const selected = selectedInstallTarget === option.value;
                        return (
                          <button
                            className={`flex items-start gap-3 rounded-md border p-3 text-left transition-colors hover:bg-muted ${selected ? "border-primary bg-accent" : ""}`}
                            key={option.value}
                            onClick={() => changeInstallTarget(option.value)}
                            type="button"
                          >
                            <Icon className="mt-0.5 size-4 text-muted-foreground" />
                            <div>
                              <div className="text-sm font-medium">{option.value === "remote" ? "Remote endpoint" : "Local runtime"}</div>
                              <div className="text-xs text-muted-foreground">
                                {option.value === "remote" ? "Connect to an existing MCP endpoint." : "Run this MCP server from a package or image."}
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            </CardContent>
          </Card>

          {connectionFields.length > 0 ? (
            <Card>
              <CardHeader><CardTitle>Connection</CardTitle></CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                {connectionFields.map((field) => (
                  <InstallFieldControl
                    field={field}
                    hasExistingValue={existingConfiguredFields.has(field.name)}
                    key={field.name}
                    onChange={(value) => setInstallValues((current) => ({ ...current, [field.name]: value }))}
                    value={installValues[field.name] ?? ""}
                  />
                ))}
              </CardContent>
            </Card>
          ) : null}

          {runtimeFields.length > 0 ? (
            <Card>
              <CardHeader><CardTitle>Runtime options</CardTitle></CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                {runtimeFields.map((field) => (
                  <InstallFieldControl
                    field={field}
                    hasExistingValue={existingConfiguredFields.has(field.name)}
                    key={field.name}
                    onChange={(value) => setInstallValues((current) => ({ ...current, [field.name]: value }))}
                    value={installValues[field.name] ?? ""}
                  />
                ))}
              </CardContent>
            </Card>
          ) : null}

          {selectedServer ? (
            <Card>
              <CardHeader className="flex-row items-center justify-between space-y-0">
                <CardTitle>Custom headers</CardTitle>
                <Button disabled={isMutating} onClick={addCustomHeader} size="sm" type="button" variant="outline">
                  <X className="size-4 rotate-45" />
                  Add header
                </Button>
              </CardHeader>
              <CardContent className="space-y-2">
                {customHeaders.length === 0 ? <div className="text-sm text-muted-foreground">No custom headers.</div> : null}
                {customHeaders.map((header) => (
                  <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]" key={header.id}>
                    <Input autoComplete="off" onChange={(event) => updateCustomHeader(header.id, { name: event.target.value })} placeholder="Header key" value={header.name} />
                    <Input autoComplete="off" onChange={(event) => updateCustomHeader(header.id, { value: event.target.value })} placeholder="Header value" type="password" value={header.value} />
                    <Button aria-label="Remove custom header" disabled={isMutating} onClick={() => removeCustomHeader(header.id)} size="icon" type="button" variant="outline">
                      <X className="size-4" />
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button disabled={isMutating} onClick={() => router.push("/install")} type="button" variant="outline">Cancel</Button>
        <Button disabled={isMutating || !selectedServer} type="submit">
          <Download className="size-4" />
          {isMutating ? "Saving" : isEdit ? "Save" : "Add"}
        </Button>
      </div>
    </form>
  );
}
