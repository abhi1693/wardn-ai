"use client";

import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileUp,
  Network,
  Package,
  Search,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type {
  MCPRegistryServerListResponse,
  MCPRegistryServerResponse,
  MCPServerInstallRequestConfigValues,
  MCPServerInstallationRead,
  SecretStoreRead,
} from "@/lib/api/generated/model";

type InstallTarget = string;
type InstallTargetKind = "remote" | "package";

type InstallTargetOption = {
  value: InstallTarget;
  kind: InstallTargetKind;
  index: number;
  label: string;
  description: string;
};

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

type FileInstallValue = {
  type: "file";
  filename: string;
  content: string;
};

type InstallValue = string | FileInstallValue;

type CustomHeader = {
  id: string;
  name: string;
  value: string;
};

type InstallFormClientProps = {
  basePath: string;
  initialInstallation?: MCPServerInstallationRead | null;
  initialInstallations: MCPServerInstallationRead[];
  initialSelectedServer?: MCPRegistryServerResponse | null;
  initialServerNextCursor?: string;
  initialServers?: MCPRegistryServerResponse[];
  secretStores: SecretStoreRead[];
};

const SERVER_PICKER_PAGE_SIZE = 12;

function installUrl(serverName: string) {
  return `/api/mcp/registry/installed-servers/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}

function encodedServerName(serverName: string) {
  return serverName.split("/").map(encodeURIComponent).join("/");
}

function serverVersionUrl(serverName: string, version: string) {
  return `/api/mcp/registry/servers/${encodedServerName(serverName)}/${encodeURIComponent(version)}`;
}

function serverVersionsUrl(serverName: string) {
  return `/api/mcp/registry/servers/${encodedServerName(serverName)}/versions`;
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

function runtimeDisplayName(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === "remote" || normalized === "streamable-http" || normalized === "sse") {
    return "Remote API";
  }
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
  return value || "Package";
}

function runtimeDetailName(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === "streamable-http") {
    return "Streamable HTTP";
  }
  if (normalized === "sse") {
    return "SSE";
  }
  return runtimeDisplayName(value);
}

function deliveryDetails(entry: MCPRegistryServerResponse) {
  const firstPackage = entry.server.packages?.[0] as Record<string, unknown> | undefined;
  const firstRemote = entry.server.remotes?.[0] as Record<string, unknown> | undefined;

  if (firstRemote) {
    const type = stringValue(firstRemote.type) || "remote";
    const url = stringValue(firstRemote.url);
    return { icon: Network, primary: runtimeDisplayName(type), secondary: url ? displayHost(url) : "" };
  }
  if (firstPackage) {
    const registryType = stringValue(firstPackage.registryType) || "package";
    return {
      icon: Package,
      primary: runtimeDisplayName(registryType),
      secondary: stringValue(firstPackage.identifier),
    };
  }
  return { icon: Package, primary: "Unspecified", secondary: "" };
}

function packageDescription(packageDefinition: Record<string, unknown>) {
  const registryType = stringValue(packageDefinition.registryType) || "package";
  const identifier = stringValue(packageDefinition.identifier);
  return [runtimeDetailName(registryType), identifier].filter(Boolean).join(" · ");
}

function remoteDescription(remote: Record<string, unknown>) {
  const type = stringValue(remote.type) || "remote";
  const url = stringValue(remote.url);
  return url ? `${runtimeDetailName(type)} · ${displayHost(url)}` : runtimeDetailName(type);
}

function installTargetOptions(entry: MCPRegistryServerResponse): InstallTargetOption[] {
  const packageOptions = (entry.server.packages ?? []).map((packageDefinition, index) => {
    const packageRecord = packageDefinition as Record<string, unknown>;
    return {
      value: `package:${index}`,
      kind: "package" as const,
      index,
      label: "Run in Kubernetes",
      description: packageDescription(packageRecord),
    };
  });
  const remoteOptions = (entry.server.remotes ?? []).map((remote, index) => {
    const remoteRecord = remote as Record<string, unknown>;
    return {
      value: `remote:${index}`,
      kind: "remote" as const,
      index,
      label: "Remote API",
      description: remoteDescription(remoteRecord),
    };
  });
  return [...packageOptions, ...remoteOptions];
}

function defaultInstallTarget(entry: MCPRegistryServerResponse): InstallTarget {
  return installTargetOptions(entry)[0]?.value ?? "package:0";
}

function installTargetFromInstallation(installation: MCPServerInstallationRead): InstallTarget {
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  if (installation.installType === "remote") {
    const transport = runtimeConfig.transport as Record<string, unknown> | undefined;
    const transportUrl = stringValue(transport?.url);
    const remoteIndex = (installation.server.remotes ?? []).findIndex((remote) => {
      const remoteRecord = remote as Record<string, unknown>;
      return stringValue(remoteRecord.url) === transportUrl;
    });
    return `remote:${remoteIndex >= 0 ? remoteIndex : 0}`;
  }

  const packageConfig = runtimeConfig.package as Record<string, unknown> | undefined;
  const packageIdentifier = stringValue(packageConfig?.identifier);
  const packageRegistryType = stringValue(packageConfig?.registryType);
  const packageIndex = (installation.server.packages ?? []).findIndex((packageDefinition) => {
    const packageRecord = packageDefinition as Record<string, unknown>;
    return (
      stringValue(packageRecord.identifier) === packageIdentifier &&
      stringValue(packageRecord.registryType).toLowerCase() === packageRegistryType.toLowerCase()
    );
  });
  return `package:${packageIndex >= 0 ? packageIndex : 0}`;
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

function uniqueServerResponses(servers: MCPRegistryServerResponse[]) {
  const byVersion = new Map<string, MCPRegistryServerResponse>();
  for (const server of servers) {
    byVersion.set(`${server.server.name}:${server.server.version}`, server);
  }
  return Array.from(byVersion.values());
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metadataRecord(entry: MCPRegistryServerResponse, key: string) {
  const serverMeta = entry.server._meta;
  if (isRecord(serverMeta?.[key])) {
    return serverMeta[key];
  }
  const responseMeta = entry._meta as unknown;
  if (isRecord(responseMeta) && isRecord(responseMeta[key])) {
    return responseMeta[key];
  }
  return null;
}

function wardnHubMetadata(entry: MCPRegistryServerResponse) {
  return (
    metadataRecord(entry, "dev.wardnai.hub/catalog") ??
    metadataRecord(entry, "ai.wardn.hub")
  );
}

function qualityScore(entry: MCPRegistryServerResponse) {
  const metadata = wardnHubMetadata(entry);
  const directScore = numberValue(entry.server.qualityScore);
  if (directScore !== null) {
    return directScore;
  }
  return metadata ? numberValue(metadata.qualityScore) : null;
}

function qualityScorePercent(score: number | null) {
  return score === null ? 0 : Math.max(0, Math.min(100, score));
}

function qualityScoreTone(score: number | null) {
  if (score === null) {
    return "bg-muted-foreground/25";
  }
  if (score >= 85) {
    return "bg-emerald-500";
  }
  if (score >= 70) {
    return "bg-lime-500";
  }
  if (score >= 50) {
    return "bg-amber-500";
  }
  return "bg-red-500";
}

function serverCategory(entry: MCPRegistryServerResponse) {
  const metadata = wardnHubMetadata(entry);
  const category = metadata ? stringValue(metadata.category) : "";
  if (category) {
    return category;
  }
  return deliveryDetails(entry).primary;
}

function serverIconUrl(entry: MCPRegistryServerResponse) {
  const icon = entry.server.icons?.find((item) => isRecord(item) && stringValue(item.url));
  return isRecord(icon) ? stringValue(icon.url) : "";
}

function installTargetKind(target: InstallTarget): InstallTargetKind {
  return target.startsWith("remote") ? "remote" : "package";
}

function installTargetIndex(target: InstallTarget) {
  const rawIndex = target.split(":")[1];
  const index = Number.parseInt(rawIndex ?? "0", 10);
  return Number.isFinite(index) && index >= 0 ? index : 0;
}

function installTargetPayloadValue(target: InstallTarget) {
  const kind = installTargetKind(target);
  const index = installTargetIndex(target);
  return index === 0 ? kind : `${kind}:${index}`;
}

function installValueConfigured(value: InstallValue | undefined) {
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  return Boolean(value?.content);
}

function installValueInputText(value: InstallValue | undefined) {
  return typeof value === "string" ? value : "";
}

function installValueFilename(value: InstallValue | undefined) {
  return typeof value === "string" ? "" : value?.filename || "";
}

function selectedInstallTargetOption(
  entry: MCPRegistryServerResponse,
  target: InstallTarget,
): InstallTargetOption {
  return installTargetOptions(entry).find((option) => option.value === target) ?? {
    value: target,
    kind: installTargetKind(target),
    index: installTargetIndex(target),
    label: installTargetKind(target) === "remote" ? "Remote API" : "Run in Kubernetes",
    description: "",
  };
}

function installFields(entry: MCPRegistryServerResponse, target: InstallTarget): InstallField[] {
  const targetKind = installTargetKind(target);
  const targetIndex = installTargetIndex(target);
  const remote = entry.server.remotes?.[targetIndex] as Record<string, unknown> | undefined;
  const remoteHeaders = Array.isArray(remote?.headers) ? (remote.headers as Record<string, unknown>[]) : [];
  const packageDefinition = entry.server.packages?.[targetIndex] as Record<string, unknown> | undefined;
  const environmentVariables = Array.isArray(packageDefinition?.environmentVariables)
    ? (packageDefinition.environmentVariables as Record<string, unknown>[])
    : [];
  const packageArguments = Array.isArray(packageDefinition?.packageArguments)
    ? (packageDefinition.packageArguments as Record<string, unknown>[])
    : [];

  const connectionFields = (targetKind === "remote" ? remoteHeaders : environmentVariables).map((field) => ({
    name: String(field.name ?? ""),
    description: String(field.description ?? ""),
    required: Boolean(field.isRequired),
    secret: Boolean(field.isSecret),
    format: String(field.format ?? "string"),
    defaultValue: String(field.default ?? ""),
    options: Array.isArray(field.options) ? field.options.map(String) : [],
    section: "connection" as const,
  }));
  const runtimeFields = targetKind === "package"
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

function defaultInstallValues(fields: InstallField[]): Record<string, InstallValue> {
  return Object.fromEntries(fields.map((field) => [field.name, field.defaultValue]));
}

function mergeInstallValues(
  fields: InstallField[],
  currentValues: Record<string, InstallValue>,
): Record<string, InstallValue> {
  return Object.fromEntries(
    fields.map((field) => [field.name, currentValues[field.name] ?? field.defaultValue])
  );
}

function configuredFieldValues(
  fields: InstallField[],
  installation: MCPServerInstallationRead,
): Record<string, InstallValue> {
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
      if (field.format === "file") {
        return [field.name, ""];
      }
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!isRecord(item)) {
          return formatApiErrorDetail(item);
        }
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== "body").join(".")
          : "";
        const message = typeof item.msg === "string" ? item.msg : formatApiErrorDetail(item);
        return location ? `${location}: ${message}` : message;
      })
      .filter(Boolean)
      .join("; ");
  }
  if (isRecord(detail)) {
    for (const key of ["detail", "message", "error"]) {
      const nested = formatApiErrorDetail(detail[key]);
      if (nested) {
        return nested;
      }
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return "";
    }
  }
  return "";
}

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown; error?: unknown };
    return (
      formatApiErrorDetail(payload.detail) ||
      formatApiErrorDetail(payload.message) ||
      formatApiErrorDetail(payload.error) ||
      fallback
    );
  } catch {
    return fallback;
  }
}

function ServerPickerCard({
  entry,
  onSelect,
}: {
  entry: MCPRegistryServerResponse;
  onSelect: () => void;
}) {
  const score = qualityScore(entry);
  const iconUrl = serverIconUrl(entry);
  const description = entry.server.description?.trim();
  const category = serverCategory(entry);

  return (
    <button
      className="flex min-h-48 w-full flex-col rounded-md border bg-white p-4 text-left transition-colors hover:border-primary/50 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={onSelect}
      type="button"
    >
      <div className="flex items-start gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted text-sm font-semibold text-muted-foreground">
          {iconUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              alt=""
              className="size-full object-cover"
              loading="lazy"
              src={iconUrl}
            />
          ) : (
            (entry.server.title || entry.server.name).slice(0, 1).toUpperCase()
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="break-words text-sm font-semibold leading-5 text-foreground">
            {entry.server.title || entry.server.name}
          </div>
          <div className="mt-0.5 break-words text-xs leading-4 text-muted-foreground">
            {category || entry.server.name}
          </div>
        </div>
      </div>

      {description ? (
        <p className="mt-4 line-clamp-4 text-sm leading-6 text-foreground">
          {description}
        </p>
      ) : (
        <div className="mt-4 text-sm leading-6 text-muted-foreground">
          No description provided.
        </div>
      )}

      <div className="mt-auto pt-4">
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="text-muted-foreground">Quality score</span>
          <span className="font-semibold text-foreground">
            {score === null ? "Pending" : `${score}/100`}
          </span>
        </div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full ${qualityScoreTone(score)}`}
            style={{ width: `${qualityScorePercent(score)}%` }}
          />
        </div>
      </div>
    </button>
  );
}

function InstallFieldControl({
  field,
  hasExistingValue = false,
  onChange,
  value,
}: {
  field: InstallField;
  hasExistingValue?: boolean;
  onChange: (value: InstallValue) => void;
  value: InstallValue;
}) {
  const inputId = `install-${field.name}`;

  if (field.format === "boolean") {
    return (
      <label className="flex items-start gap-3 rounded-md border p-3 text-sm">
        <input
          checked={installValueInputText(value) === "true"}
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

  if (field.format === "file") {
    const selectedFilename = installValueFilename(value);
    return (
      <div className="grid gap-2">
        <Label htmlFor={inputId}>
          {field.name}
          {field.required ? <span className="text-red-600"> *</span> : null}
        </Label>
        <div className="grid gap-2">
          <Input
            id={inputId}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) {
                onChange("");
                return;
              }
              void file.text().then((content) => {
                onChange({
                  type: "file",
                  filename: file.name,
                  content,
                });
              });
            }}
            type="file"
          />
          {selectedFilename ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <FileUp className="size-3.5" />
              {selectedFilename}
            </div>
          ) : hasExistingValue ? (
            <div className="text-xs text-muted-foreground">Configured file is saved.</div>
          ) : null}
        </div>
        {field.description ? <div className="text-xs leading-5 text-muted-foreground">{field.description}</div> : null}
      </div>
    );
  }

  return (
    <div className="grid gap-2">
      <Label htmlFor={inputId}>
        {field.name}
        {field.required ? <span className="text-red-600"> *</span> : null}
      </Label>
      {field.options.length > 0 || field.format === "select" ? (
        <Select onValueChange={onChange} value={installValueInputText(value)}>
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
          value={installValueInputText(value)}
        />
      )}
      {field.description ? <div className="text-xs leading-5 text-muted-foreground">{field.description}</div> : null}
    </div>
  );
}

export function InstallFormClient({
  basePath,
  initialInstallation = null,
  initialInstallations,
  initialSelectedServer = null,
  initialServerNextCursor = "",
  initialServers = [],
  secretStores,
}: InstallFormClientProps) {
  const router = useRouter();
  const isEdit = Boolean(initialInstallation);
  const [installations, setInstallations] = useState<MCPServerInstallationRead[]>(initialInstallations);
  const [serverQuery, setServerQuery] = useState("");
  const [appliedServerQuery, setAppliedServerQuery] = useState("");
  const [serverResults, setServerResults] = useState<MCPRegistryServerResponse[]>(() =>
    uniqueServerResponses(initialServers)
  );
  const [serverCurrentCursor, setServerCurrentCursor] = useState("");
  const [serverNextCursor, setServerNextCursor] = useState(initialServerNextCursor);
  const [serverPreviousCursors, setServerPreviousCursors] = useState<string[]>([]);
  const [hasSearched, setHasSearched] = useState(initialServers.length > 0);
  const [isSearching, setIsSearching] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");
  const [selectedServer, setSelectedServer] = useState<MCPRegistryServerResponse | null>(() =>
    initialInstallation
      ? serverResponseFromInstallation(initialInstallation)
      : initialSelectedServer
  );
  const [serverVersions, setServerVersions] = useState<MCPRegistryServerResponse[]>(() =>
    initialSelectedServer
      ? [initialSelectedServer]
      : initialInstallation
        ? [serverResponseFromInstallation(initialInstallation)]
        : []
  );
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
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
  const hasInitializedServerSearch = useRef(false);
  const serverSearchRequestId = useRef(0);

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
  const selectedServerName = selectedServer?.server.name ?? "";
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

  useEffect(() => {
    if (!selectedServerName) {
      return;
    }

    let cancelled = false;
    async function loadVersions() {
      setIsLoadingVersions(true);
      try {
        const response = await fetch(serverVersionsUrl(selectedServerName), {
          cache: "no-store",
        });
        if (!response.ok) {
          return;
        }
        const data = (await response.json()) as MCPRegistryServerListResponse;
        if (!cancelled) {
          setServerVersions(data.servers);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingVersions(false);
        }
      }
    }

    void loadVersions();
    return () => {
      cancelled = true;
    };
  }, [selectedServerName]);

  const loadServerOptions = useCallback(async ({
    query,
    cursor,
    previous,
  }: {
    query: string;
    cursor: string;
    previous: string[];
  }) => {
    const requestId = serverSearchRequestId.current + 1;
    serverSearchRequestId.current = requestId;
    setError("");
    setHasSearched(true);
    setIsSearching(true);
    try {
      const params = new URLSearchParams({
        limit: String(SERVER_PICKER_PAGE_SIZE),
        version: "latest",
      });
      if (query.trim()) {
        params.set("search", query.trim());
      }
      if (cursor) {
        params.set("cursor", cursor);
      }
      const response = await fetch(`/api/mcp/registry/servers?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error("Server search failed.");
      }
      const data = (await response.json()) as MCPRegistryServerListResponse;
      if (serverSearchRequestId.current !== requestId) {
        return;
      }
      setServerResults(uniqueServerResponses(data.servers));
      setAppliedServerQuery(query);
      setServerCurrentCursor(cursor);
      setServerNextCursor(data.metadata.nextCursor ?? "");
      setServerPreviousCursors(previous);
    } catch (caught) {
      if (serverSearchRequestId.current !== requestId) {
        return;
      }
      setError(caught instanceof Error ? caught.message : "Server search failed.");
    } finally {
      if (serverSearchRequestId.current === requestId) {
        setIsSearching(false);
      }
    }
  }, []);

  async function loadNextServerPage() {
    if (!serverNextCursor) {
      return;
    }
    await loadServerOptions({
      query: appliedServerQuery,
      cursor: serverNextCursor,
      previous: [...serverPreviousCursors, serverCurrentCursor],
    });
  }

  async function loadPreviousServerPage() {
    if (serverPreviousCursors.length === 0) {
      return;
    }
    const previousCursor = serverPreviousCursors.at(-1) ?? "";
    await loadServerOptions({
      query: appliedServerQuery,
      cursor: previousCursor,
      previous: serverPreviousCursors.slice(0, -1),
    });
  }

  useEffect(() => {
    if (selectedServer) {
      return;
    }
    if (!hasInitializedServerSearch.current) {
      hasInitializedServerSearch.current = true;
      return;
    }

    const timeout = window.setTimeout(() => {
      void loadServerOptions({ query: serverQuery, cursor: "", previous: [] });
    }, 250);

    return () => window.clearTimeout(timeout);
  }, [loadServerOptions, serverQuery, selectedServer]);

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
      const response = await fetch(serverVersionUrl(selectedServer.server.name, version), {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error("Server version could not be loaded.");
      }
      const server = (await response.json()) as MCPRegistryServerResponse;
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
      const response = await fetch(installUrl(selectedServer.server.name), {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, isEdit ? "Failed to save instance." : "Failed to add instance."));
      }
      const installation = (await response.json()) as MCPServerInstallationRead;
      setInstallations((current) => [...current.filter((item) => item.id !== installation.id), installation]);
      router.push(basePath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Server instance could not be saved.");
    } finally {
      setIsMutating(false);
    }
  }

  const serverPageNumber = serverPreviousCursors.length + 1;
  const serverPageStart =
    serverResults.length > 0 ? serverPreviousCursors.length * SERVER_PICKER_PAGE_SIZE + 1 : 0;
  const serverPageEnd = serverPreviousCursors.length * SERVER_PICKER_PAGE_SIZE + serverResults.length;

  return (
    <form className="space-y-5" onSubmit={submitConfiguration}>
      {error ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

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
            <div className="rounded-md border bg-white px-3 py-10 text-center text-sm text-muted-foreground">
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
