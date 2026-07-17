"use client";

import {
  ChevronLeft,
  ChevronRight,
  Download,
  Network,
  Package,
  Search,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type {
  MCPRegistryServerResponse,
  MCPOperationJobRead,
  MCPServerInstallRequest,
  MCPServerInstallRequestConfigValues,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";
import {
  organizationMcpRegistryGetServerVersion,
} from "@/lib/api/generated/organization-mcp-registry/organization-mcp-registry";
import {
  workspaceMcpRegistryGetOperationJob,
  workspaceMcpRegistryInstallServerVersion,
} from "@/lib/api/generated/workspace-mcp-registry/workspace-mcp-registry";
import {
  isOperationJobPollingCancelled,
  useOperationJobPoller,
} from "@/lib/use-operation-job";

import {
  configuredFieldNames,
  configuredFieldValues,
  defaultInstallTarget,
  defaultInstallValues,
  installFields,
  installTargetFromInstallation,
  installTargetOptions,
  installTargetPayloadValue,
  installValueConfigured,
  mergeInstallValues,
  selectedInstallTargetOption,
  serverResponseFromInstallation,
  SERVER_PICKER_PAGE_SIZE,
  type CustomHeader,
  type InstallFormClientProps,
  type InstallTarget,
  type InstallValue,
} from "./install-form-domain";
import { InstallFieldControl, ServerPickerCard } from "./install-form-fields";
import { useInstallServerPicker } from "./use-install-server-picker";



export function InstallFormClient({
  basePath,
  initialInstallation = null,
  initialInstallations,
  initialSelectedServer = null,
  initialServerNextCursor = "",
  initialServers = [],
  organizationId,
  secretStores,
  workspaceId,
}: InstallFormClientProps) {
  const router = useRouter();
  const isEdit = Boolean(initialInstallation);
  const [installations, setInstallations] = useState<MCPServerInstallationRead[]>(initialInstallations);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");
  const [jobProgress, setJobProgress] = useState("");
  const { waitForJob } = useOperationJobPoller();
  const [selectedServer, setSelectedServer] = useState<MCPRegistryServerResponse | null>(() =>
    initialInstallation
      ? serverResponseFromInstallation(initialInstallation)
      : initialSelectedServer
  );
  const {
    appliedServerQuery,
    hasSearched,
    isLoadingVersions,
    isSearching,
    loadNextServerPage,
    loadPreviousServerPage,
    serverNextCursor,
    serverPreviousCursors,
    serverQuery,
    serverResults,
    serverVersions,
    setServerQuery,
    setIsLoadingVersions,
    setServerVersions,
  } = useInstallServerPicker({
    initialNextCursor: initialServerNextCursor,
    initialServers,
    initialVersions: initialSelectedServer
      ? [initialSelectedServer]
      : initialInstallation
        ? [serverResponseFromInstallation(initialInstallation)]
        : [],
    organizationId,
    selectedServer,
    setError,
  });
  const [selectedInstallTarget, setSelectedInstallTarget] = useState<InstallTarget>(() =>
    initialInstallation
      ? installTargetFromInstallation(initialInstallation)
      : initialSelectedServer
        ? defaultInstallTarget(initialSelectedServer)
        : "package"
  );
  const initialFields = selectedServer
    ? installFields(
        selectedServer,
        initialInstallation
          ? installTargetFromInstallation(initialInstallation)
          : defaultInstallTarget(selectedServer)
      )
    : [];
  const [configName, setConfigName] = useState(() => {
    if (initialInstallation) {
      return initialInstallation.configName;
    }
    if (!initialSelectedServer) {
      return "default";
    }
    const existingConfigNames = new Set(
      initialInstallations
        .filter((installation) => installation.serverName === initialSelectedServer.server.name)
        .map((installation) => installation.configName)
    );
    return existingConfigNames.has("default") ? "" : "default";
  });
  const [installValues, setInstallValues] = useState<Record<string, InstallValue>>(() =>
    initialInstallation
      ? configuredFieldValues(initialFields, initialInstallation)
      : defaultInstallValues(initialFields)
  );
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>([]);
  const activeSecretStores = useMemo(
    () => secretStores.filter((store) => store.isActive && !store.workspaceId),
    [secretStores]
  );
  const [configSecretStoreId, setConfigSecretStoreId] = useState(activeSecretStores[0]?.id ?? "");
  const customHeaderId = useRef(0);

  const availableInstallTargets = selectedServer ? installTargetOptions(selectedServer) : [];
  const selectedInstallTargetDetails = selectedServer
    ? selectedInstallTargetOption(selectedServer, selectedInstallTarget)
    : null;
  const selectedFields = selectedServer ? installFields(selectedServer, selectedInstallTarget) : [];
  const connectionFields = selectedFields.filter((field) => field.section === "connection");
  const runtimeFields = selectedFields.filter((field) => field.section === "runtime");
  const needsSecretBackend =
    selectedFields.some((field) => field.secret || field.format === "file") ||
    customHeaders.some((header) => header.name.trim() || header.value.trim());
  const existingConfiguredFields = useMemo(() => configuredFieldNames(initialInstallation), [initialInstallation]);
  const versionOptions = useMemo(() => {
    if (!selectedServer) {
      return [];
    }
    const versions = new Map<string, MCPRegistryServerResponse>();
    versions.set(selectedServer.server.version, selectedServer);
    for (const version of serverVersions) {
      versions.set(version.server.version, version);
    }
    return Array.from(versions.values());
  }, [selectedServer, serverVersions]);

  function selectServerForInstall(server: MCPRegistryServerResponse) {
    const target = defaultInstallTarget(server);
    const existingConfigNames = new Set(
      installations
        .filter((installation) => installation.serverName === server.server.name)
        .map((installation) => installation.configName)
    );
    setSelectedServer(server);
    setServerVersions([server]);
    setSelectedInstallTarget(target);
    setConfigName(existingConfigNames.has("default") ? "" : "default");
    setInstallValues(defaultInstallValues(installFields(server, target)));
    setCustomHeaders([]);
    setError("");
  }

  async function changeServerVersion(version: string) {
    if (!selectedServer || version === selectedServer.server.version) {
      return;
    }

    setIsLoadingVersions(true);
    setError("");
    try {
      const server = await organizationMcpRegistryGetServerVersion(
        organizationId,
        selectedServer.server.name,
        version
      );
      const availableTargets = installTargetOptions(server);
      const target = availableTargets.some((option) => option.value === selectedInstallTarget)
        ? selectedInstallTarget
        : defaultInstallTarget(server);
      const fields = installFields(server, target);
      setSelectedServer(server);
      setSelectedInstallTarget(target);
      setInstallValues((current) =>
        isEdit ? mergeInstallValues(fields, current) : defaultInstallValues(fields)
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Server version could not be loaded.");
    } finally {
      setIsLoadingVersions(false);
    }
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

  function installPayloadValues(): MCPServerInstallRequestConfigValues {
    const payload: MCPServerInstallRequestConfigValues = {};
    for (const [key, value] of Object.entries(installValues)) {
      if (installValueConfigured(value)) {
        payload[key] = value;
      }
    }
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

    const missing = selectedFields.filter(
      (field) => field.required && !isEdit && !installValueConfigured(installValues[field.name])
    );
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
    if (needsSecretBackend && !configSecretStoreId) {
      setError("Secret backend is required for MCP secrets.");
      return;
    }

    setIsMutating(true);
    setError("");
    setJobProgress("Queueing installation");
    try {
      const body: Record<string, unknown> = {
        version: selectedServer.server.version,
        configName: trimmedConfigName,
        installTarget: installTargetPayloadValue(selectedInstallTarget),
        configValues: installPayloadValues(),
      };
      if (needsSecretBackend) {
        body.configSecretStoreId = configSecretStoreId;
      }
      const job = await workspaceMcpRegistryInstallServerVersion(
        organizationId,
        workspaceId,
        selectedServer.server.name,
        body as MCPServerInstallRequest
      );
      const installation = await waitForJob<MCPServerInstallationRead>({
        failureMessage: "Server installation failed.",
        fetchJob: (jobId, signal) =>
          workspaceMcpRegistryGetOperationJob(organizationId, workspaceId, jobId, { signal }),
        initialJob: job,
        onProgress: setJobProgress,
        pendingMessage: "Installation queued",
        readResult: (completedJob: MCPOperationJobRead) => {
          const result = completedJob.result?.installation;
          if (!result || typeof result !== "object" || !("id" in result)) {
            throw new Error("Installation completed without an installation result.");
          }
          return result as MCPServerInstallationRead;
        },
        timeoutMessage: "Installation is still running. Check the installation list shortly.",
      });
      setInstallations((current) => [...current.filter((item) => item.id !== installation.id), installation]);
      router.push(basePath);
      router.refresh();
    } catch (caught) {
      if (isOperationJobPollingCancelled(caught)) {
        return;
      }
      setError(caught instanceof Error ? caught.message : "Server instance could not be saved.");
    } finally {
      setIsMutating(false);
      setJobProgress("");
    }
  }

  const serverPageNumber = serverPreviousCursors.length + 1;
  const serverPageStart =
    serverResults.length > 0 ? serverPreviousCursors.length * SERVER_PICKER_PAGE_SIZE + 1 : 0;
  const serverPageEnd = serverPreviousCursors.length * SERVER_PICKER_PAGE_SIZE + serverResults.length;

  return (
    <form className="space-y-5" onSubmit={submitConfiguration}>
      {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
      {jobProgress ? (
        <AsyncFeedback variant="progress">{jobProgress}</AsyncFeedback>
      ) : null}

      {!selectedServer ? (
        <section className="space-y-4">
          <div className="grid gap-2">
            <Label htmlFor="install-server-search">Server</Label>
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                className="pl-8"
                id="install-server-search"
                onChange={(event) => setServerQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                  }
                }}
                placeholder="Search supported servers"
                type="search"
                value={serverQuery}
              />
            </div>
          </div>

          {serverResults.length === 0 ? (
            <div
              aria-atomic="true"
              aria-busy={isSearching}
              aria-live="polite"
              className="rounded-md border bg-white px-3 py-10 text-center text-sm text-muted-foreground"
              role="status"
            >
              {isSearching ? "Loading supported servers" : hasSearched ? "No servers found" : "No supported MCP servers are registered yet"}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {serverResults.map((entry) => (
                <ServerPickerCard
                  entry={entry}
                  key={`${entry.server.name}:${entry.server.version}`}
                  onSelect={() => selectServerForInstall(entry)}
                />
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <div className="text-muted-foreground">
              {serverResults.length > 0 ? (
                <>
                  Showing {serverPageStart}-{serverPageEnd}
                  {appliedServerQuery ? ` for "${appliedServerQuery}"` : ""}
                </>
              ) : (
                "No servers to display"
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                disabled={isSearching || serverPreviousCursors.length === 0}
                onClick={() => void loadPreviousServerPage()}
                size="sm"
                type="button"
                variant="ghost"
              >
                <ChevronLeft className="size-4" />
                Previous
              </Button>
              <div className="min-w-16 whitespace-nowrap text-center text-sm font-medium text-muted-foreground">
                Page {serverPageNumber}
              </div>
              <Button
                disabled={isSearching || !serverNextCursor}
                onClick={() => void loadNextServerPage()}
                size="sm"
                type="button"
                variant="ghost"
              >
                Next
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </section>
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
                      setServerVersions([]);
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
                <div className="grid gap-2">
                  <Label htmlFor="install-server-version">Version</Label>
                  <Select
                    disabled={isLoadingVersions || versionOptions.length <= 1}
                    onValueChange={(value) => void changeServerVersion(value)}
                    value={selectedServer.server.version}
                  >
                    <SelectTrigger id="install-server-version">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {versionOptions.map((version) => (
                        <SelectItem key={version.server.version} value={version.server.version}>
                          <span className="flex items-center gap-2">
                            <span>{version.server.version}</span>
                            {version._meta["io.modelcontextprotocol.registry/official"].isLatest ? (
                              <span className="text-muted-foreground">Default</span>
                            ) : null}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {needsSecretBackend ? (
                  <div className="grid gap-2 md:col-span-2">
                    <Label htmlFor="install-secret-backend">Secret backend</Label>
                    {activeSecretStores.length > 0 ? (
                      <Select onValueChange={setConfigSecretStoreId} value={configSecretStoreId}>
                        <SelectTrigger id="install-secret-backend">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {activeSecretStores.map((store) => (
                            <SelectItem key={store.id} value={store.id}>
                              {store.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <div className="flex min-h-9 items-center rounded-md border bg-muted/30 px-3 text-sm text-muted-foreground">
                        No active secret backend
                      </div>
                    )}
                  </div>
                ) : null}
                {isEdit ? (
                  <div className="grid gap-2 md:col-span-2">
                    <Label>Install target</Label>
                    <div className="flex min-h-9 items-center gap-2 rounded-md border bg-muted/30 px-3 text-sm">
                      {selectedInstallTargetDetails?.kind === "remote" ? (
                        <Network className="size-4 text-muted-foreground" />
                      ) : (
                        <Package className="size-4 text-muted-foreground" />
                      )}
                      <span className="min-w-0">
                        <span className="block font-medium">
                          {selectedInstallTargetDetails?.label ?? "Run in Kubernetes"}
                        </span>
                        {selectedInstallTargetDetails?.description ? (
                          <span className="block truncate text-xs text-muted-foreground">
                            {selectedInstallTargetDetails.description}
                          </span>
                        ) : null}
                      </span>
                    </div>
                  </div>
                ) : availableInstallTargets.length > 1 ? (
                  <div className="grid gap-2 md:col-span-2">
                    <Label>Install target</Label>
                    <div className="grid gap-2 md:grid-cols-2">
                      {availableInstallTargets.map((option) => {
                        const Icon = option.kind === "remote" ? Network : Package;
                        const selected = selectedInstallTarget === option.value;
                        return (
                          <button
                            className={`flex items-start gap-3 rounded-md border p-3 text-left transition-colors hover:bg-muted ${selected ? "border-primary bg-accent" : ""}`}
                            key={option.value}
                            onClick={() => changeInstallTarget(option.value)}
                            type="button"
                          >
                            <Icon className="mt-0.5 size-4 text-muted-foreground" />
                            <div className="min-w-0">
                              <div className="text-sm font-medium">{option.label}</div>
                              <div className="break-all text-xs text-muted-foreground">{option.description}</div>
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
        <Button disabled={isMutating} onClick={() => router.push(basePath)} type="button" variant="outline">Cancel</Button>
        <Button disabled={isMutating || !selectedServer} type="submit">
          <Download className="size-4" />
          {isMutating ? "Saving" : isEdit ? "Save" : "Add"}
        </Button>
      </div>
    </form>
  );
}
