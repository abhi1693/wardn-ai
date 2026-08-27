"use client";

import {
  ChevronLeft,
  ChevronRight,
  Download,
  Network,
  Package,
  Search,
  Server,
  Shield,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent, ReactNode } from "react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/atoms/button";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { focusFirstInvalidFormControl } from "@/components/molecules/form-error-summary";
import { StickyFormActions } from "@/components/organisms/sticky-form-actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import { Input } from "@/components/atoms/input";
import { Label } from "@/components/atoms/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/select";
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
import { useFormSafety } from "@/hooks/use-form-safety";

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
  hubServerHref,
  mergeInstallValues,
  networkPolicyFromInstallation,
  networkPolicyPayloadValue,
  selectedInstallTargetOption,
  serverResponseFromInstallation,
  serverHasRemoteMcpEndpoints,
  SERVER_PICKER_PAGE_SIZE,
  type CustomHeader,
  type InstallFormClientProps,
  type InstallTarget,
  type InstallValue,
  type NetworkPolicyCustomEgressFormState,
  type NetworkPolicyFormState,
} from "./install-form-domain";
import { InstallFieldControl, ServerPickerCard } from "./install-form-fields";
import { useInstallServerPicker } from "./use-install-server-picker";


type RuntimePolicyToggleProps = {
  checked: boolean;
  description: string;
  disabled?: boolean;
  icon: ReactNode;
  onChange: (checked: boolean) => void;
  title: string;
};

function RuntimePolicyToggle({
  checked,
  description,
  disabled = false,
  icon,
  onChange,
  title,
}: RuntimePolicyToggleProps) {
  return (
    <label className="flex min-h-20 items-start gap-3 rounded-md border bg-muted/20 p-3 text-sm">
      <input
        checked={checked}
        className="mt-1 size-4"
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      <span className="flex min-w-0 gap-3">
        <span className="mt-0.5 text-muted-foreground">{icon}</span>
        <span className="min-w-0">
          <span className="block font-medium">{title}</span>
          <span className="mt-1 block leading-5 text-muted-foreground">{description}</span>
        </span>
      </span>
    </label>
  );
}


export function InstallFormClient({
  basePath,
  initialInstallation = null,
  initialInstallations,
  initialSelectedServer = null,
  initialServerNextCursor = "",
  initialServers = [],
  organizationId,
  packageRuntimeProvider,
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
  const [networkPolicy, setNetworkPolicy] = useState<NetworkPolicyFormState>(() =>
    networkPolicyFromInstallation(initialInstallation)
  );
  const [customHeaders, setCustomHeaders] = useState<CustomHeader[]>([]);
  const activeSecretStores = useMemo(
    () => secretStores.filter((store) => store.isActive && !store.workspaceId),
    [secretStores]
  );
  const [configSecretStoreId, setConfigSecretStoreId] = useState(activeSecretStores[0]?.id ?? "");
  const formValue = {
    configName,
    configSecretStoreId,
    customHeaders,
    installValues,
    networkPolicy,
    selectedInstallTarget,
    selectedServer: selectedServer
      ? `${selectedServer.server.name}:${selectedServer.server.version}`
      : null,
  };
  const [initialFormValue] = useState(formValue);
  const { confirmNavigation, isDirty } = useFormSafety({
    currentValue: formValue,
    formId: "install-form",
    initialValue: initialFormValue,
    isSaving: isMutating,
  });
  const customHeaderId = useRef(0);
  const customEgressId = useRef(networkPolicy.customEgress.length);

  const availableInstallTargets = selectedServer ? installTargetOptions(selectedServer) : [];
  const selectedInstallTargetDetails = selectedServer
    ? selectedInstallTargetOption(selectedServer, selectedInstallTarget)
    : null;
  const selectedFields = selectedServer ? installFields(selectedServer, selectedInstallTarget) : [];
  const connectionFields = selectedFields.filter((field) => field.section === "connection");
  const runtimeFields = selectedFields.filter((field) => field.section === "runtime");
  const hasMultipleInstallTargets = availableInstallTargets.length > 1;
  const selectedInstallTargetLabel = selectedInstallTargetDetails
    ? [selectedInstallTargetDetails.label, selectedInstallTargetDetails.description]
        .filter(Boolean)
        .join(" · ")
    : "";
  const selectedServerHubHref = selectedServer ? hubServerHref(selectedServer) : "";
  const showNetworkPolicyControls =
    selectedInstallTargetDetails?.kind === "package" &&
    packageRuntimeProvider.trim().toLowerCase() === "kubernetes";
  const showRemoteMcpEgressControl =
    showNetworkPolicyControls && serverHasRemoteMcpEndpoints(selectedServer);
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
      setError(caught instanceof Error ? caught.message : "Connection version could not be loaded.");
    } finally {
      setIsLoadingVersions(false);
    }
  }

  function changeInstallTarget(target: InstallTarget) {
    if (!selectedServer) {
      return;
    }
    setSelectedInstallTarget(target);
    const fields = installFields(selectedServer, target);
    setInstallValues((current) =>
      isEdit ? mergeInstallValues(fields, current) : defaultInstallValues(fields)
    );
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

  function updateNetworkPolicy(patch: Partial<NetworkPolicyFormState>) {
    setNetworkPolicy((current) => ({ ...current, ...patch }));
  }

  function addCustomEgressRule() {
    customEgressId.current += 1;
    setNetworkPolicy((current) => ({
      ...current,
      customEgress: [
        ...current.customEgress,
        {
          id: `custom-egress-${customEgressId.current}`,
          destinationType: "cidr",
          label: "",
          cidr: "",
          domain: "",
          ports: "443",
        },
      ],
    }));
  }

  function updateCustomEgressRule(
    id: string,
    patch: Partial<NetworkPolicyCustomEgressFormState>
  ) {
    setNetworkPolicy((current) => ({
      ...current,
      customEgress: current.customEgress.map((rule) =>
        rule.id === id ? { ...rule, ...patch } : rule
      ),
    }));
  }

  function removeCustomEgressRule(id: string) {
    setNetworkPolicy((current) => ({
      ...current,
      customEgress: current.customEgress.filter((rule) => rule.id !== id),
    }));
  }

  function installPayloadValues(): MCPServerInstallRequestConfigValues {
    const payload: MCPServerInstallRequestConfigValues = {};
    for (const field of selectedFields) {
      const value = installValues[field.name];
      if (installValueConfigured(value)) {
        payload[field.name] = value;
        continue;
      }
      if (
        typeof value === "string" &&
        !field.secret &&
        field.format !== "file" &&
        field.defaultValue.trim().length > 0 &&
        value.trim().length === 0
      ) {
        payload[field.name] = "";
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
      setError("Select a connection first.");
      focusFirstInvalidFormControl("install-form", "install-server-search");
      return;
    }

    const trimmedConfigName = configName.trim();
    if (!trimmedConfigName) {
      setError("Instance name is required.");
      focusFirstInvalidFormControl("install-form", "install-config-name");
      return;
    }

    const duplicate = installations.some(
      (installation) =>
        installation.id !== initialInstallation?.id &&
        installation.serverName === selectedServer.server.name &&
        installation.configName === trimmedConfigName
    );
    if (duplicate) {
      setError("An instance with this name already exists for the selected connection.");
      focusFirstInvalidFormControl("install-form", "install-config-name");
      return;
    }

    const missing = selectedFields.filter((field) => {
      if (!field.required || installValueConfigured(installValues[field.name])) {
        return false;
      }
      return !(isEdit && existingConfiguredFields.has(field.name));
    });
    if (missing.length > 0) {
      setError(`Missing required settings: ${missing.map((field) => field.name).join(", ")}`);
      focusFirstInvalidFormControl("install-form", `install-${missing[0].name}`);
      return;
    }

    const incompleteCustomHeaders = customHeaders
      .filter((header) => header.name.trim() || header.value.trim())
      .filter((header) => !header.name.trim() || !header.value.trim());
    if (incompleteCustomHeaders.length > 0) {
      setError("Custom headers require both a key and a value.");
      focusFirstInvalidFormControl(
        "install-form",
        `${incompleteCustomHeaders[0].id}-name`
      );
      return;
    }
    if (needsSecretBackend && !configSecretStoreId) {
      setError("Secret backend is required for connection secrets.");
      focusFirstInvalidFormControl("install-form", "install-secret-backend");
      return;
    }
    let networkPolicyPayload = null;
    if (showNetworkPolicyControls) {
      try {
        networkPolicyPayload = networkPolicyPayloadValue(networkPolicy, {
          includeRemoteMcpEgress: showRemoteMcpEgressControl,
        });
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Runtime policy settings are invalid.");
        return;
      }
    }

    setIsMutating(true);
    setError("");
    setJobProgress("Queueing connection setup");
    try {
      const body: Record<string, unknown> = {
        version: selectedServer.server.version,
        configName: trimmedConfigName,
        installTarget: installTargetPayloadValue(selectedInstallTarget),
        configValues: installPayloadValues(),
      };
      if (networkPolicyPayload) {
        body.networkPolicy = networkPolicyPayload;
      }
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
        failureMessage: "Connection setup failed.",
        fetchJob: (jobId, signal) =>
          workspaceMcpRegistryGetOperationJob(organizationId, workspaceId, jobId, { signal }),
        initialJob: job,
        onProgress: setJobProgress,
        pendingMessage: "Connection setup queued",
        readResult: (completedJob: MCPOperationJobRead) => {
          const result = completedJob.result?.installation;
          if (!result || typeof result !== "object" || !("id" in result)) {
            throw new Error("Connection setup completed without a result.");
          }
          return result as MCPServerInstallationRead;
        },
        timeoutMessage: "Connection setup is still running. Check connections shortly.",
      });
      setInstallations((current) => [...current.filter((item) => item.id !== installation.id), installation]);
      router.push(basePath);
      router.refresh();
    } catch (caught) {
      if (isOperationJobPollingCancelled(caught)) {
        return;
      }
      setError(caught instanceof Error ? caught.message : "Connection could not be saved.");
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
    <form className="space-y-5" id="install-form" onSubmit={submitConfiguration}>
      {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
      {jobProgress ? (
        <AsyncFeedback variant="progress">{jobProgress}</AsyncFeedback>
      ) : null}

      {!selectedServer ? (
        <section className="space-y-4">
          <div className="grid gap-1.5">
            <div>
              <Label htmlFor="install-server-search">Choose a connection</Label>
              <p className="mt-1 text-sm text-muted-foreground">
                Select a supported MCP server, then configure its runtime and credentials.
              </p>
            </div>
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
                placeholder="Search by server, title, or use case"
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
              className="rounded-md border bg-card px-3 py-10 text-center text-sm text-muted-foreground"
              role="status"
            >
              {isSearching ? "Loading supported connections" : hasSearched ? "No connections found" : "No supported connections are registered yet"}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
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
                "No connections to display"
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
            <CardHeader><CardTitle>Connection Source</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start justify-between gap-3 rounded-md bg-muted/50 p-3">
                <div className="min-w-0">
                  <div className="font-medium">{selectedServer.server.title || selectedServer.server.name}</div>
                  {selectedServerHubHref ? (
                    <a
                      className="mt-0.5 block break-all text-xs text-primary underline-offset-4 hover:underline"
                      href={selectedServerHubHref}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {selectedServer.server.name}
                    </a>
                  ) : (
                    <div className="mt-0.5 break-all text-xs text-muted-foreground">
                      {selectedServer.server.name}
                    </div>
                  )}
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
                {selectedInstallTargetDetails ? (
                  <>
                    <div className="grid gap-2">
                      <Label htmlFor="install-runtime">Runtime</Label>
                      {hasMultipleInstallTargets ? (
                        <Select
                          disabled={isMutating}
                          onValueChange={changeInstallTarget}
                          value={selectedInstallTarget}
                        >
                          <SelectTrigger id="install-runtime">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {availableInstallTargets.map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                {[option.label, option.description].filter(Boolean).join(" · ")}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <div
                          className="flex min-h-9 items-center gap-2 rounded-md border bg-muted/30 px-3 text-sm"
                          id="install-runtime"
                        >
                          {selectedInstallTargetDetails.kind === "remote" ? (
                            <Network className="size-4 text-muted-foreground" />
                          ) : (
                            <Package className="size-4 text-muted-foreground" />
                          )}
                          <span className="truncate font-medium">
                            {selectedInstallTargetLabel || selectedInstallTargetDetails.label}
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="grid gap-2" data-testid="install-target-details">
                      <Label>{selectedInstallTargetDetails.referenceLabel}</Label>
                      <div className="min-h-9 rounded-md border bg-muted/30 px-3 py-2 text-sm">
                        <div className="break-all font-medium">
                          {selectedInstallTargetDetails.referenceValue}
                        </div>
                        {selectedInstallTargetDetails.versionValue ? (
                          <div className="text-xs text-muted-foreground">
                            {selectedInstallTargetDetails.versionLabel}:{" "}
                            {selectedInstallTargetDetails.versionValue}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </>
                ) : null}
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
              <CardHeader><CardTitle>Advanced Runtime Options</CardTitle></CardHeader>
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

          {showNetworkPolicyControls ? (
            <Card>
              <CardHeader><CardTitle>Runtime Access</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-3">
                  <RuntimePolicyToggle
                    checked={networkPolicy.allowRuntimeDependencyEgress}
                    description="Allow package runtimes to reach their required package registries and runtime dependency endpoints."
                    disabled={!networkPolicy.denyOtherEgress}
                    icon={<Package className="size-4" />}
                    onChange={(checked) => updateNetworkPolicy({ allowRuntimeDependencyEgress: checked })}
                    title="Runtime dependencies"
                  />
                  <RuntimePolicyToggle
                    checked={networkPolicy.allowKubernetesApi}
                    description="Allow this runtime to reach the in-cluster Kubernetes API. Wardn discovers the service address, ports, and CNI policy type."
                    disabled={!networkPolicy.denyOtherEgress}
                    icon={<Server className="size-4" />}
                    onChange={(checked) => updateNetworkPolicy({ allowKubernetesApi: checked })}
                    title="Kubernetes API"
                  />
                  {showRemoteMcpEgressControl ? (
                    <RuntimePolicyToggle
                      checked={networkPolicy.allowRemoteMcpEgress}
                      description="Allow this package runtime to reach remote MCP endpoints declared by the selected server."
                      disabled={!networkPolicy.denyOtherEgress}
                      icon={<Network className="size-4" />}
                      onChange={(checked) => updateNetworkPolicy({ allowRemoteMcpEgress: checked })}
                      title="Remote MCP endpoints"
                    />
                  ) : null}
                  <RuntimePolicyToggle
                    checked={networkPolicy.denyOtherEgress}
                    description="Apply default-deny egress except for Wardn-managed DNS and the selected access intents."
                    icon={<Shield className="size-4" />}
                    onChange={(checked) => updateNetworkPolicy({ denyOtherEgress: checked })}
                    title="Deny other egress"
                  />
                </div>

                {!networkPolicy.denyOtherEgress ? (
                  <AsyncFeedback variant="info">
                    Saving with default-deny off creates a Wardn-managed allow-all egress
                    policy for this connection.
                  </AsyncFeedback>
                ) : null}

                {networkPolicy.denyOtherEgress ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <Label>Custom egress</Label>
                        <p className="mt-1 text-sm text-muted-foreground">
                          Add CIDR or domain destinations this runtime may reach.
                        </p>
                      </div>
                      <Button onClick={addCustomEgressRule} size="sm" type="button" variant="outline">
                        <X className="size-4 rotate-45" />
                        Add egress
                      </Button>
                    </div>

                    {networkPolicy.customEgress.length === 0 ? (
                      <div className="rounded-md border bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
                        No custom egress rules.
                      </div>
                    ) : null}

                    {networkPolicy.customEgress.map((rule) => (
                      <div className="grid gap-3 rounded-md border p-3 md:grid-cols-[minmax(8rem,.8fr)_minmax(0,1fr)_minmax(0,1.3fr)_minmax(8rem,.7fr)_auto]" key={rule.id}>
                        <div className="space-y-1.5">
                          <Label htmlFor={`${rule.id}-type`}>Type</Label>
                          <Select
                            onValueChange={(value) =>
                              updateCustomEgressRule(rule.id, {
                                destinationType: value === "domain" ? "domain" : "cidr",
                                cidr: value === "domain" ? "" : rule.cidr,
                                domain: value === "domain" ? rule.domain : "",
                              })
                            }
                            value={rule.destinationType}
                          >
                            <SelectTrigger id={`${rule.id}-type`}>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="cidr">CIDR</SelectItem>
                              <SelectItem value="domain">Domain</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-1.5">
                          <Label htmlFor={`${rule.id}-label`}>Label</Label>
                          <Input
                            id={`${rule.id}-label`}
                            onChange={(event) => updateCustomEgressRule(rule.id, { label: event.target.value })}
                            placeholder="unifi-access"
                            value={rule.label}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label htmlFor={`${rule.id}-destination`}>
                            {rule.destinationType === "domain" ? "Domain" : "CIDR"}
                          </Label>
                          <Input
                            id={`${rule.id}-destination`}
                            onChange={(event) =>
                              updateCustomEgressRule(
                                rule.id,
                                rule.destinationType === "domain"
                                  ? { domain: event.target.value }
                                  : { cidr: event.target.value },
                              )
                            }
                            placeholder={rule.destinationType === "domain" ? "api.example.com" : "192.168.3.1/32"}
                            value={rule.destinationType === "domain" ? rule.domain : rule.cidr}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label htmlFor={`${rule.id}-ports`}>Ports</Label>
                          <Input
                            id={`${rule.id}-ports`}
                            onChange={(event) => updateCustomEgressRule(rule.id, { ports: event.target.value })}
                            placeholder="443"
                            value={rule.ports}
                          />
                        </div>
                        <div className="flex items-end">
                          <Button
                            aria-label="Remove custom egress"
                            onClick={() => removeCustomEgressRule(rule.id)}
                            size="icon"
                            type="button"
                            variant="outline"
                          >
                            <X className="size-4" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
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
                    <Input autoComplete="off" id={`${header.id}-name`} onChange={(event) => updateCustomHeader(header.id, { name: event.target.value })} placeholder="Header key" value={header.name} />
                    <Input autoComplete="off" id={`${header.id}-value`} onChange={(event) => updateCustomHeader(header.id, { value: event.target.value })} placeholder="Header value" type="password" value={header.value} />
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

      <StickyFormActions position="bottom">
        <Button
          disabled={isMutating}
          onClick={() => {
            if (confirmNavigation()) {
              router.push(basePath);
            }
          }}
          type="button"
          variant="outline"
        >
          Cancel
        </Button>
        {selectedServer ? (
          <Button disabled={isMutating || (isEdit && !isDirty)} type="submit">
            <Download className="size-4" />
            {isMutating
              ? isEdit
                ? "Saving"
                : "Creating"
              : isEdit
                ? "Save"
                : "Create connection"}
          </Button>
        ) : null}
      </StickyFormActions>
    </form>
  );
}
