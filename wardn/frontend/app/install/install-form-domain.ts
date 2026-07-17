import { Network, Package } from "lucide-react";

import type {
  MCPRegistryServerResponse,
  MCPServerInstallationRead,
  SecretStoreRead,
} from "@/lib/api/generated/model";

export type InstallTarget = string;
export type InstallTargetKind = "remote" | "package";

export type InstallTargetOption = {
  value: InstallTarget;
  kind: InstallTargetKind;
  index: number;
  label: string;
  description: string;
};

export type InstallField = {
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
  format: string;
  defaultValue: string;
  options: string[];
  section: "connection" | "runtime";
};

export type FileInstallValue = {
  type: "file";
  filename: string;
  content: string;
};

export type InstallValue = string | FileInstallValue;

export type CustomHeader = {
  id: string;
  name: string;
  value: string;
};

export type InstallFormClientProps = {
  basePath: string;
  initialInstallation?: MCPServerInstallationRead | null;
  initialInstallations: MCPServerInstallationRead[];
  initialSelectedServer?: MCPRegistryServerResponse | null;
  initialServerNextCursor?: string;
  initialServers?: MCPRegistryServerResponse[];
  organizationId: string;
  secretStores: SecretStoreRead[];
  workspaceId: string;
};

export const SERVER_PICKER_PAGE_SIZE = 12;

export function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

export function displayHost(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function runtimeDisplayName(value: string) {
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

export function runtimeDetailName(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === "streamable-http") {
    return "Streamable HTTP";
  }
  if (normalized === "sse") {
    return "SSE";
  }
  return runtimeDisplayName(value);
}

export function deliveryDetails(entry: MCPRegistryServerResponse) {
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

export function packageDescription(packageDefinition: Record<string, unknown>) {
  const registryType = stringValue(packageDefinition.registryType) || "package";
  const identifier = stringValue(packageDefinition.identifier);
  return [runtimeDetailName(registryType), identifier].filter(Boolean).join(" · ");
}

export function remoteDescription(remote: Record<string, unknown>) {
  const type = stringValue(remote.type) || "remote";
  const url = stringValue(remote.url);
  return url ? `${runtimeDetailName(type)} · ${displayHost(url)}` : runtimeDetailName(type);
}

export function installTargetOptions(entry: MCPRegistryServerResponse): InstallTargetOption[] {
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

export function defaultInstallTarget(entry: MCPRegistryServerResponse): InstallTarget {
  return installTargetOptions(entry)[0]?.value ?? "package:0";
}

export function installTargetFromInstallation(installation: MCPServerInstallationRead): InstallTarget {
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

export function serverResponseFromInstallation(installation: MCPServerInstallationRead): MCPRegistryServerResponse {
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

export function uniqueServerResponses(servers: MCPRegistryServerResponse[]) {
  const byVersion = new Map<string, MCPRegistryServerResponse>();
  for (const server of servers) {
    byVersion.set(`${server.server.name}:${server.server.version}`, server);
  }
  return Array.from(byVersion.values());
}

export function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function metadataRecord(entry: MCPRegistryServerResponse, key: string) {
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

export function wardnHubMetadata(entry: MCPRegistryServerResponse) {
  return (
    metadataRecord(entry, "dev.wardnai.hub/catalog") ??
    metadataRecord(entry, "ai.wardn.hub")
  );
}

export function qualityScore(entry: MCPRegistryServerResponse) {
  const metadata = wardnHubMetadata(entry);
  const directScore = numberValue(entry.server.qualityScore);
  if (directScore !== null) {
    return directScore;
  }
  return metadata ? numberValue(metadata.qualityScore) : null;
}

export function qualityScorePercent(score: number | null) {
  return score === null ? 0 : Math.max(0, Math.min(100, score));
}

export function qualityScoreTone(score: number | null) {
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

export function serverCategory(entry: MCPRegistryServerResponse) {
  const metadata = wardnHubMetadata(entry);
  const category = metadata ? stringValue(metadata.category) : "";
  if (category) {
    return category;
  }
  return deliveryDetails(entry).primary;
}

export function serverIconUrl(entry: MCPRegistryServerResponse) {
  const icon = entry.server.icons?.find((item) => isRecord(item) && stringValue(item.url));
  return isRecord(icon) ? stringValue(icon.url) : "";
}

export function installTargetKind(target: InstallTarget): InstallTargetKind {
  return target.startsWith("remote") ? "remote" : "package";
}

export function installTargetIndex(target: InstallTarget) {
  const rawIndex = target.split(":")[1];
  const index = Number.parseInt(rawIndex ?? "0", 10);
  return Number.isFinite(index) && index >= 0 ? index : 0;
}

export function installTargetPayloadValue(target: InstallTarget) {
  const kind = installTargetKind(target);
  const index = installTargetIndex(target);
  return index === 0 ? kind : `${kind}:${index}`;
}

export function installValueConfigured(value: InstallValue | undefined) {
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  return Boolean(value?.content);
}

export function installValueInputText(value: InstallValue | undefined) {
  return typeof value === "string" ? value : "";
}

export function installValueFilename(value: InstallValue | undefined) {
  return typeof value === "string" ? "" : value?.filename || "";
}

export function selectedInstallTargetOption(
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

export function installFields(entry: MCPRegistryServerResponse, target: InstallTarget): InstallField[] {
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

export function defaultInstallValues(fields: InstallField[]): Record<string, InstallValue> {
  return Object.fromEntries(fields.map((field) => [field.name, field.defaultValue]));
}

export function mergeInstallValues(
  fields: InstallField[],
  currentValues: Record<string, InstallValue>,
): Record<string, InstallValue> {
  return Object.fromEntries(
    fields.map((field) => [field.name, currentValues[field.name] ?? field.defaultValue])
  );
}

export function configuredFieldValues(
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

export function configuredFieldNames(installation: MCPServerInstallationRead | null) {
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

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

