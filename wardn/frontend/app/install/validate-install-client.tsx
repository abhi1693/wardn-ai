"use client";

import { ApiError, apiRawFetch } from "@/lib/api/client";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  CircleStop,
  Edit2,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Terminal,
  Wrench,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/atoms/badge";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { Button } from "@/components/atoms/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import { Input } from "@/components/atoms/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/select";
import type {
  MCPRuntimeInstallationControlResponse,
  MCPServerInstallationRead,
  MCPServerInstallationToolValidationResponse,
  MCPServerToolRead,
} from "@/lib/api/generated/model";
import {
  workspaceMcpRuntimeGetInstallationState,
  workspaceMcpRuntimeRedeployInstallation,
  workspaceMcpRuntimeRestartInstallation,
  workspaceMcpRuntimeStartInstallation,
  workspaceMcpRuntimeStopInstallation,
} from "@/lib/api/generated/workspace-mcp-runtime/workspace-mcp-runtime";
import {
  workspaceMcpRegistryListInstalledServerTools,
  workspaceMcpRegistryValidateInstalledServerTool,
} from "@/lib/api/generated/workspace-mcp-registry/workspace-mcp-registry";
import { responseErrorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

type ToolInputProperty = {
  name: string;
  required: boolean;
  type: string;
  description: string;
  enumValues: string[];
  schema: Record<string, unknown>;
};

type ValidationArgumentValue = string | boolean;

type RuntimeAction = "start" | "stop" | "restart" | "redeploy";

type ArgumentFieldError = {
  field: string;
  message: string;
};

type RefreshOptions = {
  reportError?: boolean;
  showLoading?: boolean;
};

const mcpToolDiscoveryTimeoutMs = 120_000;

function caughtMessage(caught: unknown, fallback: string) {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

function installationRuntimeKind(installation: MCPServerInstallationRead) {
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const configuredKind = typeof runtimeConfig.kind === "string" ? runtimeConfig.kind : "";
  return (configuredKind || installation.installType || "").trim().toLowerCase();
}

function runtimeStatusLabel(status: string | undefined) {
  if (!status) {
    return "Not started";
  }
  if (status === "tools_responding") {
    return "Tools responding";
  }
  return status.replace(/_/g, " ");
}

function runtimeStatusBadgeVariant(
  status: string | undefined
): "success" | "secondary" | "destructive" | "outline" {
  if (status === "idle" || status === "running" || status === "ready") {
    return "success";
  }
  if (status === "tools_responding") {
    return "success";
  }
  if (status === "failed" || status === "not_ready") {
    return "destructive";
  }
  if (status === "stopped" || status === "expired") {
    return "secondary";
  }
  return "outline";
}

function runtimePackageRegistryType(installation: MCPServerInstallationRead) {
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const registryType = runtimeConfig.registryType;
  if (typeof registryType === "string" && registryType.trim()) {
    return registryType.trim().toLowerCase();
  }
  const packageConfig = runtimeConfig.package;
  if (isRecord(packageConfig)) {
    const packageRegistryType = packageConfig.registryType;
    if (typeof packageRegistryType === "string" && packageRegistryType.trim()) {
      return packageRegistryType.trim().toLowerCase();
    }
    const packageIdentifier = packageConfig.identifier;
    if (typeof packageIdentifier === "string" && packageIdentifier.trim()) {
      return installation.installType.trim().toLowerCase();
    }
  }
  return "";
}

function packageRegistryPolicyDetail(installation: MCPServerInstallationRead) {
  const registryType = runtimePackageRegistryType(installation);
  if (registryType === "pypi" || registryType === "uvx") {
    return "PyPI registry egress";
  }
  if (registryType === "npm") {
    return "npm registry egress";
  }
  return "";
}

function installationHasRemoteMcpDestinations(installation: MCPServerInstallationRead) {
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const rawPolicy = runtimeConfig.networkPolicy;
  if (isRecord(rawPolicy) && Array.isArray(rawPolicy.remoteDestinations)) {
    return rawPolicy.remoteDestinations.length > 0;
  }
  return Boolean(
    installation.server.remotes?.some((remote) =>
      typeof (remote as Record<string, unknown>).url === "string" &&
      Boolean(((remote as Record<string, unknown>).url as string).trim())
    )
  );
}

function runtimePolicyDetails(installation: MCPServerInstallationRead) {
  if (installation.runtimeProvider !== "kubernetes") {
    return [];
  }
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const rawPolicy = runtimeConfig.networkPolicy;
  const packageRegistryDetail = packageRegistryPolicyDetail(installation);
  if (!isRecord(rawPolicy)) {
    return [
      "Default-deny egress",
      ...(installationHasRemoteMcpDestinations(installation) ? ["Remote MCP endpoint egress"] : []),
      ...(packageRegistryDetail ? [packageRegistryDetail] : []),
    ];
  }
  const denyOtherEgress = rawPolicy.denyOtherEgress ?? rawPolicy.isolationEnabled;
  if (denyOtherEgress === false) {
    return ["Allow all egress"];
  }
  const details = ["Default-deny egress"];
  if (rawPolicy.allowRemoteMcpEgress !== false && installationHasRemoteMcpDestinations(installation)) {
    details.push("Remote MCP endpoint egress");
  }
  const allowRuntimeDependencyEgress =
    rawPolicy.allowRuntimeDependencyEgress ?? rawPolicy.allowRemoteMcpEgress;
  if (allowRuntimeDependencyEgress !== false && packageRegistryDetail) {
    details.push(packageRegistryDetail);
  }
  if (rawPolicy.allowKubernetesApi === true || rawPolicy.inClusterKubernetesApi === true) {
    details.push("Kubernetes API");
  }
  if (rawPolicy.publicEgress === true) {
    details.push("Legacy public egress");
  }
  if (rawPolicy.privateEgress === true) {
    details.push("Legacy private egress");
  }
  if (Array.isArray(rawPolicy.customEgress) && rawPolicy.customEgress.length > 0) {
    details.push("Custom egress");
  }
  return details;
}

type GatewayRpcResponse = {
  result?: {
    structuredContent?: {
      tools?: Array<{
        serverName?: string;
        toolName?: string;
        title?: string;
        description?: string;
        inputSchema?: Record<string, unknown>;
      }>;
      nextCursor?: string;
    };
  };
  error?: {
    message?: string;
  };
};

type ValidateInstallClientProps = {
  basePath: string;
  installation: MCPServerInstallationRead;
  organizationId: string;
  workspaceId: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function metadataRecord(document: MCPServerInstallationRead["server"], key: string) {
  const metadata = document._meta;
  if (isRecord(metadata) && isRecord(metadata[key])) {
    return metadata[key];
  }
  return null;
}

function hubServerHref(installation: MCPServerInstallationRead) {
  for (const server of [installation.server, installation.latestServer]) {
    const metadata = metadataRecord(server, "wardnCatalogSource");
    if (!metadata || stringValue(metadata.provider) !== "wardn_hub") {
      continue;
    }
    const baseUrl = stringValue(metadata.baseUrl).trim();
    if (!baseUrl) {
      continue;
    }
    try {
      const serverPath = server.name.split("/").map(encodeURIComponent).join("/");
      return new URL(`/servers/${serverPath}`, baseUrl.replace(/\/+$/, "/")).toString();
    } catch {
      return "";
    }
  }
  return "";
}

function editInstallUrl(basePath: string, installationId: string) {
  return `${basePath}/${encodeURIComponent(installationId)}/edit`;
}

function formatRefreshTime(value: Date | null) {
  if (!value) {
    return "Not refreshed";
  }
  return value.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function refreshDetail(value: Date | null) {
  return value ? `Refreshed ${formatRefreshTime(value)}` : "Not refreshed";
}

function runtimeStillBooting(status: string | undefined) {
  return !status || ["creating", "pending", "starting", "not_ready", "running"].includes(status);
}

function schemaVariants(schema: Record<string, unknown>) {
  for (const key of ["anyOf", "oneOf", "allOf"] as const) {
    const variants = schema[key];
    if (Array.isArray(variants)) {
      return variants.filter(isRecord);
    }
  }
  return [];
}

function isNullSchema(schema: Record<string, unknown>) {
  const rawType = schema.type;
  return rawType === "null" || (Array.isArray(rawType) && rawType.every((item) => item === "null"));
}

function effectiveSchema(schema: Record<string, unknown>): Record<string, unknown> {
  const variants = schemaVariants(schema).filter((variant) => !isNullSchema(variant));
  if (variants.length === 0) {
    return schema;
  }
  const firstVariant = effectiveSchema(variants[0]);
  return {
    ...firstVariant,
    description: schema.description ?? firstVariant.description,
    default: schema.default ?? firstVariant.default,
  };
}

function schemaType(schema: Record<string, unknown>) {
  const resolvedSchema = effectiveSchema(schema);
  const rawType = resolvedSchema.type;
  if (Array.isArray(rawType)) {
    return rawType.find((item) => typeof item === "string" && item !== "null") ?? "object";
  }
  return typeof rawType === "string" && rawType !== "null" ? rawType : "object";
}

function hasNullVariant(schema: Record<string, unknown>) {
  return schemaVariants(schema).some(isNullSchema);
}

function exampleValueForSchema(schema: unknown, depth = 0): unknown {
  if (!isRecord(schema) || depth > 3) {
    return "";
  }

  const resolvedSchema = effectiveSchema(schema);
  const type = schemaType(resolvedSchema);
  if (resolvedSchema.default !== undefined && resolvedSchema.default !== null) {
    return resolvedSchema.default;
  }
  if (type === "boolean") {
    return false;
  }
  if (type === "integer" || type === "number") {
    return 0;
  }
  if (type === "array") {
    return [];
  }
  if (type === "object") {
    return argumentsTemplateForSchema(resolvedSchema, depth + 1);
  }
  return "";
}

function requiredInputNames(schema: unknown) {
  if (!isRecord(schema) || !Array.isArray(schema.required)) {
    return [];
  }
  return schema.required.filter((item): item is string => typeof item === "string");
}

function inputProperties(schema: unknown) {
  if (!isRecord(schema) || !isRecord(schema.properties)) {
    return [];
  }

  const requiredNames = new Set(requiredInputNames(schema));
  return Object.entries(schema.properties).map(([name, propertySchema]) => {
    const property = isRecord(propertySchema) ? propertySchema : {};
    const resolvedProperty = effectiveSchema(property);
    return {
      name,
      required: requiredNames.has(name),
      type: schemaType(resolvedProperty),
      description:
        typeof property.description === "string"
          ? property.description
          : typeof resolvedProperty.description === "string"
            ? resolvedProperty.description
            : "",
      enumValues: Array.isArray(resolvedProperty.enum)
        ? resolvedProperty.enum.filter((item): item is string => typeof item === "string")
        : [],
      schema: property,
    };
  });
}

function argumentsTemplateForSchema(schema: unknown, depth = 0): Record<string, unknown> {
  if (!isRecord(schema)) {
    return {};
  }

  const properties = schema.properties;
  if (!isRecord(properties)) {
    return {};
  }

  const requiredNames = requiredInputNames(schema);
  const names = requiredNames.length > 0 ? requiredNames : Object.keys(properties);
  return names.reduce<Record<string, unknown>>((result, name) => {
    result[name] = exampleValueForSchema(properties[name], depth + 1);
    return result;
  }, {});
}

function initialArgumentValuesForSchema(schema: unknown): Record<string, ValidationArgumentValue> {
  return inputProperties(schema).reduce<Record<string, ValidationArgumentValue>>((result, input) => {
    const example = exampleValueForSchema(input.schema);
    if (input.type === "boolean") {
      result[input.name] = Boolean(example);
    } else if (input.type === "object" || input.type === "array") {
      result[input.name] =
        !input.required && isRecord(input.schema) && hasNullVariant(input.schema)
          ? ""
          : JSON.stringify(example, null, 2);
    } else if (input.enumValues.length > 0) {
      result[input.name] = input.enumValues[0] ?? "";
    } else if (typeof example === "number") {
      result[input.name] = String(example);
    } else {
      result[input.name] = "";
    }
    return result;
  }, {});
}

function parseArgumentsFromFields(
  inputs: ToolInputProperty[],
  values: Record<string, ValidationArgumentValue>
): { argumentsValue: Record<string, unknown>; error: ArgumentFieldError | null } {
  const argumentsValue: Record<string, unknown> = {};

  for (const input of inputs) {
    const rawValue = values[input.name];

    if (input.type === "boolean") {
      argumentsValue[input.name] = rawValue === true;
      continue;
    }

    const value = typeof rawValue === "string" ? rawValue.trim() : "";
    if (!value) {
      if (input.required) {
        return {
          argumentsValue: {},
          error: { field: input.name, message: `Required argument missing: ${input.name}` },
        };
      }
      continue;
    }

    if (input.type === "integer" || input.type === "number") {
      const parsed = Number(value);
      if (!Number.isFinite(parsed) || (input.type === "integer" && !Number.isInteger(parsed))) {
        return {
          argumentsValue: {},
          error: { field: input.name, message: `${input.name} must be a valid ${input.type}.` },
        };
      }
      argumentsValue[input.name] = parsed;
      continue;
    }

    if (input.type === "object" || input.type === "array") {
      try {
        const parsed = JSON.parse(value) as unknown;
        if (input.type === "object" && (!isRecord(parsed) || Array.isArray(parsed))) {
          return {
            argumentsValue: {},
            error: { field: input.name, message: `${input.name} must be a JSON object.` },
          };
        }
        if (input.type === "array" && !Array.isArray(parsed)) {
          return {
            argumentsValue: {},
            error: { field: input.name, message: `${input.name} must be a JSON array.` },
          };
        }
        argumentsValue[input.name] = parsed;
      } catch {
        return {
          argumentsValue: {},
          error: { field: input.name, message: `${input.name} must contain valid JSON.` },
        };
      }
      continue;
    }

    argumentsValue[input.name] = value;
  }

  return { argumentsValue, error: null };
}

function validateRequiredArguments(
  inputs: ToolInputProperty[],
  values: Record<string, ValidationArgumentValue>
): ArgumentFieldError | null {
  for (const input of inputs) {
    if (!input.required || input.type === "boolean") {
      continue;
    }

    const rawValue = values[input.name];
    const value = typeof rawValue === "string" ? rawValue.trim() : "";
    if (!value) {
      return {
        field: input.name,
        message: "This field is required",
      };
    }
  }

  return null;
}

async function loadToolsFromGateway(
  installation: MCPServerInstallationRead,
  organizationId: string,
  workspaceId: string
): Promise<MCPServerToolRead[]> {
  const tools: MCPServerToolRead[] = [];
  let cursor = "";
  let requestId = 1;

  do {
    const response = await apiRawFetch(
      `/api/v1/organizations/${encodeURIComponent(
        organizationId
      )}/workspaces/${encodeURIComponent(workspaceId)}/mcp/gateway`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: requestId,
          method: "tools/call",
          params: {
            name: "search_mcp_tools",
            arguments: {
              serverName: installation.serverName,
              limit: 25,
              ...(cursor ? { cursor } : {}),
            },
          },
        }),
        cache: "no-store",
        timeoutMs: mcpToolDiscoveryTimeoutMs,
      }
    );

    if (!response.ok) {
      throw new Error(await responseErrorMessage(response, "Tools could not be loaded."));
    }

    const payload = (await response.json()) as GatewayRpcResponse;
    if (payload.error?.message) {
      throw new Error(payload.error.message);
    }

    const pageTools = payload.result?.structuredContent?.tools ?? [];
    tools.push(
      ...pageTools
        .filter((tool) => typeof tool.toolName === "string" && tool.toolName.trim())
        .map((tool) => ({
          serverName: tool.serverName || installation.serverName,
          serverVersion: installation.installedVersion,
          toolName: tool.toolName || "",
          title: tool.title || tool.toolName || "",
          description: tool.description || "",
          inputSchema: tool.inputSchema || { type: "object" },
          outputSchema: undefined,
          annotations: {},
        }))
    );
    cursor = payload.result?.structuredContent?.nextCursor ?? "";
    requestId += 1;
  } while (cursor);

  return tools;
}

export function ValidateInstallClient({
  basePath,
  installation,
  organizationId,
  workspaceId,
}: ValidateInstallClientProps) {
  const [tools, setTools] = useState<MCPServerToolRead[]>([]);
  const [toolSearch, setToolSearch] = useState("");
  const [selectedToolName, setSelectedToolName] = useState("");
  const [argumentValues, setArgumentValues] = useState<Record<string, ValidationArgumentValue>>({});
  const [argumentError, setArgumentError] = useState<ArgumentFieldError | null>(null);
  const [result, setResult] = useState<MCPServerInstallationToolValidationResponse | null>(null);
  const [runtimeState, setRuntimeState] =
    useState<MCPRuntimeInstallationControlResponse | null>(null);
  const [runtimeError, setRuntimeError] = useState("");
  const [toolsError, setToolsError] = useState("");
  const [validationError, setValidationError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshNotice, setRefreshNotice] = useState("");
  const [isLoadingTools, setIsLoadingTools] = useState(true);
  const [isLoadingRuntime, setIsLoadingRuntime] = useState(true);
  const [isValidating, setIsValidating] = useState(false);
  const [runtimeAction, setRuntimeAction] = useState<RuntimeAction | null>(null);
  const [lastRuntimeRefreshAt, setLastRuntimeRefreshAt] = useState<Date | null>(null);
  const [lastToolsRefreshAt, setLastToolsRefreshAt] = useState<Date | null>(null);
  const isRemoteInstallation = installationRuntimeKind(installation) === "remote";

  const selectedTool = useMemo(
    () => tools.find((tool) => tool.toolName === selectedToolName) ?? null,
    [selectedToolName, tools]
  );
  const selectedInputs = useMemo(
    () => inputProperties(selectedTool?.inputSchema),
    [selectedTool]
  );
  const filteredTools = useMemo(() => {
    const query = toolSearch.trim().toLocaleLowerCase();
    if (!query) {
      return tools;
    }
    return tools.filter((tool) =>
      [tool.title, tool.toolName, tool.description]
        .filter(Boolean)
        .some((value) => value.toLocaleLowerCase().includes(query))
    );
  }, [toolSearch, tools]);

  function selectTool(tool: MCPServerToolRead) {
    setSelectedToolName(tool.toolName);
    setArgumentValues(initialArgumentValuesForSchema(tool.inputSchema));
    setArgumentError(null);
    setResult(null);
  }

  const fetchRuntimeState = useCallback(
    () =>
      workspaceMcpRuntimeGetInstallationState(
        organizationId,
        workspaceId,
        installation.id
      ),
    [installation.id, organizationId, workspaceId]
  );

  const applyLoadedTools = useCallback((nextTools: MCPServerToolRead[]) => {
    setTools(nextTools);
    if (nextTools.length > 0) {
      const firstTool = nextTools[0];
      setSelectedToolName(firstTool.toolName);
      setArgumentValues(initialArgumentValuesForSchema(firstTool.inputSchema));
    } else {
      setSelectedToolName("");
      setArgumentValues({});
    }
    setArgumentError(null);
    setResult(null);
  }, []);

  const fetchTools = useCallback(async () => {
    try {
      const data = await workspaceMcpRegistryListInstalledServerTools(
        organizationId,
        workspaceId,
        installation.id,
        { timeoutMs: mcpToolDiscoveryTimeoutMs }
      );
      const sortedTools = [...data.tools].sort((left, right) =>
        left.toolName.localeCompare(right.toolName)
      );
      return sortedTools;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        try {
          const fallbackTools = await loadToolsFromGateway(
            installation,
            organizationId,
            workspaceId
          );
          const sortedFallbackTools = fallbackTools.sort((left, right) =>
            left.toolName.localeCompare(right.toolName)
          );
          return sortedFallbackTools;
        } catch (fallbackError) {
          caught = fallbackError;
        }
      }
      throw caught;
    }
  }, [installation, organizationId, workspaceId]);

  const loadRuntimeState = useCallback(async (options: RefreshOptions = {}) => {
    const { reportError = true, showLoading = true } = options;
    if (showLoading) {
      setIsLoadingRuntime(true);
    }
    try {
      const data = await fetchRuntimeState();
      setRuntimeState(data);
      setRuntimeError("");
      setLastRuntimeRefreshAt(new Date());
      return true;
    } catch (caught) {
      if (reportError) {
        setRuntimeError(caughtMessage(caught, "Runtime state could not be loaded."));
      }
      return false;
    } finally {
      setIsLoadingRuntime(false);
    }
  }, [fetchRuntimeState]);

  const loadTools = useCallback(async (options: RefreshOptions = {}) => {
    const { reportError = true, showLoading = true } = options;
    if (showLoading) {
      setIsLoadingTools(true);
    }
    try {
      applyLoadedTools(await fetchTools());
      setToolsError("");
      setLastToolsRefreshAt(new Date());
      return true;
    } catch (caught) {
      if (reportError) {
        setToolsError(caughtMessage(caught, "Tools could not be loaded."));
      }
      return false;
    } finally {
      setIsLoadingTools(false);
    }
  }, [applyLoadedTools, fetchTools]);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialRuntimeState() {
      if (isRemoteInstallation) {
        setIsLoadingRuntime(false);
        return;
      }
      try {
        const data = await fetchRuntimeState();
        if (!cancelled) {
          setRuntimeState(data);
          setRuntimeError("");
          setLastRuntimeRefreshAt(new Date());
        }
      } catch (caught) {
        if (!cancelled) {
          setRuntimeError(caughtMessage(caught, "Runtime state could not be loaded."));
        }
      } finally {
        if (!cancelled) {
          setIsLoadingRuntime(false);
        }
      }
    }

    void loadInitialRuntimeState();

    return () => {
      cancelled = true;
    };
  }, [fetchRuntimeState, isRemoteInstallation]);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialTools() {
      try {
        const nextTools = await fetchTools();
        if (!cancelled) {
          applyLoadedTools(nextTools);
          setToolsError("");
          setLastToolsRefreshAt(new Date());
        }
      } catch (caught) {
        if (!cancelled) {
          setToolsError(caughtMessage(caught, "Tools could not be loaded."));
        }
      } finally {
        if (!cancelled) {
          setIsLoadingTools(false);
        }
      }
    }

    void loadInitialTools();

    return () => {
      cancelled = true;
    };
  }, [applyLoadedTools, fetchTools]);

  const runtimeSession = runtimeState?.runtimeSession ?? null;
  const runtimeBusy = isLoadingRuntime || runtimeAction !== null;
  const runtimeActionLabels: Record<RuntimeAction, string> = {
    start: "started",
    stop: "stopped",
    restart: "restarted",
    redeploy: "redeployed",
  };

  async function runRuntimeAction(action: RuntimeAction) {
    const actions = {
      start: workspaceMcpRuntimeStartInstallation,
      stop: workspaceMcpRuntimeStopInstallation,
      restart: workspaceMcpRuntimeRestartInstallation,
      redeploy: workspaceMcpRuntimeRedeployInstallation,
    };

    setRuntimeAction(action);
    setRuntimeError("");
    setToolsError("");
    setValidationError("");
    setNotice("");
    setRefreshNotice("");
    setResult(null);
    try {
      const data = await actions[action](organizationId, workspaceId, installation.id);
      setRuntimeState(data);
      setNotice(`Runtime ${runtimeActionLabels[action]}.`);
      if (action === "stop") {
        setTools([]);
        setSelectedToolName("");
        setArgumentValues({});
        setArgumentError(null);
      } else {
        const toolsRefreshed = await loadTools({ reportError: false, showLoading: false });
        if (!toolsRefreshed) {
          setRefreshNotice(
            "Runtime control succeeded, but tools are still not ready to refresh. Try again in a few seconds."
          );
        }
      }
      const runtimeRefreshed = await loadRuntimeState({ reportError: false, showLoading: false });
      if (!runtimeRefreshed) {
        setRefreshNotice(
          "Runtime control succeeded, but the latest runtime state could not refresh. Try again in a few seconds."
        );
      }
    } catch (caught) {
      setRuntimeError(
        caughtMessage(caught, `Runtime could not be ${runtimeActionLabels[action]}.`)
      );
    } finally {
      setRuntimeAction(null);
    }
  }

  async function validateTool() {
    const toolName = selectedToolName.trim();
    if (!toolName) {
      setValidationError("Tool name is required.");
      return;
    }

    const requiredError = validateRequiredArguments(selectedInputs, argumentValues);
    if (requiredError) {
      setArgumentError(requiredError);
      return;
    }

    setIsValidating(true);
    setValidationError("");
    setArgumentError(null);
    setResult(null);
    try {
      const parsedArguments = parseArgumentsFromFields(selectedInputs, argumentValues);
      if (parsedArguments.error) {
        setArgumentError(parsedArguments.error);
        return;
      }

      const data = await workspaceMcpRegistryValidateInstalledServerTool(
        organizationId,
        workspaceId,
        installation.id,
        {
          toolName,
          arguments: parsedArguments.argumentsValue,
        }
      );
      setResult(data);
    } catch (caught) {
      setValidationError(caught instanceof Error ? caught.message : "Tool validation failed.");
    } finally {
      setIsValidating(false);
    }
  }

  const runtimeStatus = runtimeSession?.status;
  const runtimeHealth = runtimeState?.health ?? null;
  const isRemoteRuntime = isRemoteInstallation;
  const rawRuntimeDisplayStatus = runtimeHealth?.status || runtimeStatus;
  const toolsResponding = tools.length > 0 && !toolsError;
  const runtimeDisplayStatus =
    toolsResponding &&
    (runtimeError ||
      rawRuntimeDisplayStatus === "failed" ||
      rawRuntimeDisplayStatus === "not_ready" ||
      (runtimeHealth !== null && !runtimeHealth.ready))
      ? "tools_responding"
      : rawRuntimeDisplayStatus;
  const healthDetails = runtimeHealth?.details ?? {};
  const desiredReplicas =
    typeof healthDetails.desiredReplicas === "number" ? healthDetails.desiredReplicas : null;
  const readyReplicas =
    typeof healthDetails.readyReplicas === "number" ? healthDetails.readyReplicas : null;
  const runtimeDetails = [
    runtimeSession?.namespace ? `Namespace ${runtimeSession.namespace}` : "",
    runtimeSession?.podName ? `Pod ${runtimeSession.podName}` : "",
    desiredReplicas !== null && readyReplicas !== null
      ? `Ready ${readyReplicas}/${desiredReplicas}`
      : "",
  ].filter(Boolean);
  const policyDetails = runtimePolicyDetails(installation);
  const runtimeIsStopped =
    runtimeDisplayStatus === "stopped" ||
    runtimeDisplayStatus === "expired" ||
    (!runtimeDisplayStatus && !isLoadingRuntime);
  const canStartRuntime =
    !isRemoteRuntime && (Boolean(runtimeState?.canStart) || runtimeIsStopped) && !runtimeBusy;
  const canStopRuntime =
    !isRemoteRuntime && Boolean(runtimeState?.canStop) && !runtimeBusy && !runtimeIsStopped;
  const canRestartRuntime =
    !isRemoteRuntime && Boolean(runtimeState?.canRestart) && !runtimeBusy && !runtimeIsStopped;
  const canRedeployRuntime = !isRemoteRuntime && Boolean(runtimeState?.canRedeploy) && !runtimeBusy;
  const editHref = editInstallUrl(basePath, installation.id);
  const hubHref = hubServerHref(installation);
  const runtimeProvider = runtimeSession?.runtimeProvider || installation.runtimeProvider;
  const runtimeMessage =
    runtimeDisplayStatus === "tools_responding"
      ? "Tool discovery is responding. The Kubernetes health read may still be catching up."
      : runtimeHealth?.message || runtimeError || runtimeSession?.lastError || "";
  const discoveryDetail = toolsResponding
    ? `${tools.length} discovered`
    : isLoadingTools
      ? "Discovery running"
      : toolsError
        ? "Discovery failed"
        : "No tools discovered";
  const runtimeReplicaDetail =
    desiredReplicas !== null && readyReplicas !== null
      ? `${readyReplicas}/${desiredReplicas} replicas ready`
      : runtimeSession?.podName
        ? "Single runtime pod"
        : "No live pod reported";
  const toolPanelTitle = selectedTool?.title || selectedTool?.toolName || (
    isLoadingTools ? "Discovering tools" : "Select a tool"
  );
  const emptyToolMessage = isLoadingTools
    ? "Tool discovery is still running."
    : toolsError
      ? "Tool discovery failed. Resolve the error above, then try again."
      : tools.length === 0
        ? "No tools are available for validation yet."
        : "Select a tool to configure validation arguments.";
  const validateDisabledReason = isValidating
    ? "Validation is running."
    : isLoadingTools
      ? "Tool discovery is still running."
      : !selectedToolName
        ? "Select a tool before validating."
        : "";
  const metricCards = [
    {
      detail: installation.configName,
      icon: Activity,
      label: "Connection",
      value: installation.status || "installed",
    },
    {
      detail: refreshDetail(lastToolsRefreshAt),
      icon: Wrench,
      label: "Tools",
      value: discoveryDetail,
    },
    ...(!isRemoteRuntime
      ? [
          {
            detail: refreshDetail(lastRuntimeRefreshAt),
            icon: runtimeDisplayStatus === "tools_responding" ? AlertTriangle : Activity,
            label: "Runtime",
            value: runtimeStatusLabel(runtimeDisplayStatus),
          },
          {
            detail: policyDetails.join(", ") || "No runtime policy details",
            icon: ShieldCheck,
            label: "Egress Policy",
            value: policyDetails.length > 0 ? `${policyDetails.length} rules` : "Default",
          },
        ]
      : []),
  ];
  const headerStatusLabel = isRemoteRuntime
    ? installation.status || "enabled"
    : isLoadingRuntime
      ? "Loading"
      : runtimeStatusLabel(runtimeDisplayStatus);
  const headerStatusVariant = isRemoteRuntime
    ? "outline"
    : runtimeStatusBadgeVariant(runtimeDisplayStatus);

  useEffect(() => {
    const shouldPollRuntime =
      !isRemoteRuntime &&
      (runtimeAction !== null ||
        runtimeStillBooting(rawRuntimeDisplayStatus) ||
        Boolean(runtimeError && !toolsResponding));
    const shouldPollTools =
      !toolsResponding &&
      !isLoadingTools &&
      (runtimeStillBooting(rawRuntimeDisplayStatus) || !rawRuntimeDisplayStatus);
    if (!shouldPollRuntime && !shouldPollTools) {
      return;
    }
    const intervalId = window.setInterval(() => {
      if (shouldPollRuntime) {
        void loadRuntimeState({ reportError: false, showLoading: false });
      }
      if (shouldPollTools) {
        void loadTools({ reportError: false, showLoading: false });
      }
    }, 5_000);
    return () => window.clearInterval(intervalId);
  }, [
    isLoadingTools,
    isRemoteRuntime,
    loadRuntimeState,
    loadTools,
    rawRuntimeDisplayStatus,
    runtimeAction,
    runtimeError,
    toolsResponding,
  ]);

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden rounded-md border-border bg-card shadow-none">
        <CardContent className="p-0">
          <div className="flex flex-col gap-4 border-b border-border px-5 py-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={headerStatusVariant}>
                  {headerStatusLabel}
                </Badge>
                {!isRemoteRuntime ? <Badge variant="outline">{runtimeProvider}</Badge> : null}
                <Badge variant="outline">{installation.installType}</Badge>
                {installation.updateAvailable ? (
                  <Badge variant="secondary">Update available</Badge>
                ) : null}
              </div>
              <h2 className="mt-3 break-words text-2xl font-semibold leading-8 text-foreground">
                {installation.server.title || installation.serverName}
              </h2>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
                <span>{installation.configName}</span>
                <span>{installation.serverName}</span>
                <span>Version {installation.installedVersion}</span>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {hubHref ? (
                <Button asChild size="sm" variant="outline">
                  <a href={hubHref} rel="noreferrer" target="_blank">
                    <ExternalLink className="size-4" />
                    View in Hub
                  </a>
                </Button>
              ) : null}
              <Button asChild size="sm" variant="outline">
                <Link href={editHref}>
                  <Edit2 className="size-4" />
                  Edit
                </Link>
              </Button>
            </div>
          </div>
          <div
            className={cn(
              "grid grid-cols-1 divide-y divide-border md:divide-x md:divide-y-0",
              isRemoteRuntime ? "md:grid-cols-2" : "md:grid-cols-4"
            )}
          >
            {metricCards.map((card) => {
              const Icon = card.icon;
              return (
                <div className="min-h-28 p-4" key={card.label}>
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    <Icon className="size-3.5" />
                    {card.label}
                  </div>
                  <div className="mt-3 truncate text-lg font-semibold leading-6 text-foreground">
                    {card.value}
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                    {card.detail}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {!isRemoteRuntime ? (
        <Card className="rounded-md border-border bg-card shadow-none">
          <CardContent className="flex flex-col gap-4 p-5 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  Runtime Control
                </span>
                <Badge
                  variant={
                    isLoadingRuntime
                      ? "outline"
                      : runtimeStatusBadgeVariant(runtimeDisplayStatus)
                  }
                >
                  {isLoadingRuntime ? "Loading" : runtimeStatusLabel(runtimeDisplayStatus)}
                </Badge>
                <span className="text-xs text-muted-foreground">{runtimeReplicaDetail}</span>
              </div>
              {runtimeDetails.length > 0 ? (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {runtimeDetails.map((detail) => (
                    <span className="break-all" key={detail}>
                      {detail}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-1.5">
                {policyDetails.map((detail) => (
                  <Badge key={detail} variant="outline">
                    {detail}
                  </Badge>
                ))}
              </div>
              {runtimeMessage ? (
                <p className="max-w-4xl text-xs leading-5 text-muted-foreground">
                  {runtimeMessage}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!canStartRuntime}
                onClick={() => void runRuntimeAction("start")}
                title="Start runtime"
                type="button"
                variant="outline"
              >
                {runtimeAction === "start" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
                Start
              </Button>
              <Button
                disabled={!canStopRuntime}
                onClick={() => void runRuntimeAction("stop")}
                title="Stop runtime"
                type="button"
                variant="destructive"
              >
                {runtimeAction === "stop" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <CircleStop className="size-4" />
                )}
                Stop
              </Button>
              <Button
                disabled={!canRestartRuntime}
                onClick={() => void runRuntimeAction("restart")}
                title="Restart runtime"
                type="button"
                variant="secondary"
              >
                {runtimeAction === "restart" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <RefreshCw className="size-4" />
                )}
                Restart
              </Button>
              <Button
                disabled={!canRedeployRuntime}
                onClick={() => void runRuntimeAction("redeploy")}
                title="Redeploy runtime"
                type="button"
                variant="secondary"
              >
                {runtimeAction === "redeploy" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <RotateCcw className="size-4" />
                )}
                Redeploy
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {runtimeError && runtimeDisplayStatus !== "tools_responding" ? (
        <AsyncFeedback className="rounded-md px-4 py-3" variant="error">
          {runtimeError}
        </AsyncFeedback>
      ) : null}
      {toolsError ? (
        <AsyncFeedback className="rounded-md px-4 py-3" variant="error">
          {toolsError}
        </AsyncFeedback>
      ) : null}
      {validationError ? (
        <AsyncFeedback className="rounded-md px-4 py-3" variant="error">
          {validationError}
        </AsyncFeedback>
      ) : null}
      {notice ? (
        <AsyncFeedback className="rounded-md px-4 py-3" variant="success">
          {notice}
        </AsyncFeedback>
      ) : null}
      {refreshNotice ? (
        <AsyncFeedback className="rounded-md px-4 py-3" variant="info">
          {refreshNotice}
        </AsyncFeedback>
      ) : null}

      <div className="grid grid-cols-12 items-start gap-6">
        <Card className="col-span-12 max-h-[600px] overflow-hidden rounded-md border-border bg-card shadow-none lg:col-span-3">
          <CardHeader className="border-b border-border p-4">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                Tools
              </CardTitle>
              <Badge variant={toolsResponding ? "success" : "outline"}>
                {isLoadingTools ? "Loading" : tools.length}
              </Badge>
            </div>
            <div className="relative mt-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="h-10 rounded-md border-border bg-background pl-10 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20"
                disabled={isLoadingTools || tools.length === 0}
                onChange={(event) => setToolSearch(event.target.value)}
                placeholder="Search tools"
                value={toolSearch}
              />
            </div>
          </CardHeader>
          <CardContent className="max-h-[508px] overflow-y-auto px-0 pb-4 pt-0">
            {isLoadingTools ? (
              <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading tools
              </div>
            ) : tools.length === 0 ? (
              <div className="p-4 text-sm text-muted-foreground">
                No tools were discovered for this server.
              </div>
            ) : filteredTools.length === 0 ? (
              <div className="p-4 text-sm text-muted-foreground">
                No tools match this search.
              </div>
            ) : (
              <div className="divide-y divide-border">
                {filteredTools.map((tool) => (
                  <button
                    className={
                      tool.toolName === selectedToolName
                        ? "block w-full border-l-4 border-primary bg-muted px-4 py-3 text-left"
                        : "block w-full border-l-4 border-transparent px-4 py-3 text-left transition-colors hover:bg-muted/60"
                    }
                    key={tool.toolName}
                    onClick={() => selectTool(tool)}
                    type="button"
                  >
                    <span className="block truncate text-sm font-semibold leading-5 text-foreground">
                      {tool.title || tool.toolName}
                    </span>
                    {tool.description ? (
                      <span className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                        {tool.description}
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="col-span-12 space-y-6 lg:col-span-9">
          <Card className="overflow-hidden rounded-md border-border bg-card shadow-none">
            <CardHeader className="border-b border-border p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-xl font-semibold leading-7 tracking-normal text-foreground">
                    {toolPanelTitle}
                  </CardTitle>
                  {selectedTool?.toolName ? (
                    <div className="mt-1 font-mono text-xs text-muted-foreground">
                      {selectedTool.toolName}
                    </div>
                  ) : null}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5 p-5">
              {!selectedTool ? (
                <div className="flex min-h-48 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
                  <div className="flex items-center gap-2">
                    {isLoadingTools ? <Loader2 className="size-4 animate-spin" /> : null}
                    {emptyToolMessage}
                  </div>
                </div>
              ) : (
                <>
                  {selectedTool.description ? (
                    <div className="space-y-3">
                      <p className="whitespace-pre-wrap text-sm leading-5 text-foreground/80">
                        {selectedTool.description}
                      </p>
                    </div>
                  ) : null}

                  {selectedInputs.length === 0 ? (
                    <div className="rounded-md border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
                      This tool does not declare input fields.
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {selectedInputs.map((input) => {
                        const inputId = `validation-argument-${input.name}`;
                        const errorId = `${inputId}-error`;
                        const value = argumentValues[input.name];
                        const fieldError =
                          argumentError?.field === input.name ? argumentError.message : "";

                        return (
                          <div className="space-y-3" key={input.name}>
                            <div className="flex items-end justify-between gap-3">
                              <div className="flex min-h-6 items-center gap-2">
                                <label
                                  className="text-xs font-semibold leading-4 text-foreground"
                                  htmlFor={inputId}
                                >
                                  {input.name}
                                  {input.required ? <span className="text-red-600"> *</span> : null}
                                </label>
                                {input.description ? (
                                  <span
                                    aria-label={`${input.name} help`}
                                    className="inline-flex text-muted-foreground"
                                    title={input.description}
                                  >
                                    <CircleHelp className="size-4" />
                                  </span>
                                ) : null}
                              </div>
                              <span className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                                {input.type}
                              </span>
                            </div>

                            {input.type === "boolean" ? (
                              <label
                                className={cn(
                                  "flex h-11 items-center gap-2 rounded-md border border-border bg-background px-4 text-sm",
                                  fieldError && "!border-red-500"
                                )}
                              >
                                <input
                                  aria-describedby={fieldError ? errorId : undefined}
                                  aria-invalid={Boolean(fieldError)}
                                  checked={value === true}
                                  id={inputId}
                                  onChange={(event) => {
                                    setArgumentValues((current) => ({
                                      ...current,
                                      [input.name]: event.target.checked,
                                    }));
                                    setArgumentError(null);
                                  }}
                                  type="checkbox"
                                />
                                Enabled
                              </label>
                            ) : input.enumValues.length > 0 ? (
                              <Select
                                onValueChange={(value) => {
                                  setArgumentValues((current) => ({
                                    ...current,
                                    [input.name]: value,
                                  }));
                                  setArgumentError(null);
                                }}
                                value={typeof value === "string" ? value : ""}
                              >
                                <SelectTrigger
                                  aria-describedby={fieldError ? errorId : undefined}
                                  aria-invalid={Boolean(fieldError)}
                                  className={cn(
                                    "h-12 rounded-md border-border bg-background px-4 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20",
                                    fieldError &&
                                      "!border-red-500 focus-visible:!border-red-600 focus-visible:!ring-red-100"
                                  )}
                                  id={inputId}
                                >
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {input.enumValues.map((option) => (
                                    <SelectItem key={option} value={option}>
                                      {option}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : input.type === "object" || input.type === "array" ? (
                              <textarea
                                aria-describedby={fieldError ? errorId : undefined}
                                aria-invalid={Boolean(fieldError)}
                                className={cn(
                                  "min-h-32 w-full rounded-md border border-border bg-background px-4 py-3 font-mono text-sm outline-none transition-all focus:border-primary focus:ring-1 focus:ring-primary/20",
                                  fieldError && "!border-red-500 focus:!border-red-600 focus:!ring-red-100"
                                )}
                                id={inputId}
                                onChange={(event) => {
                                  setArgumentValues((current) => ({
                                    ...current,
                                    [input.name]: event.target.value,
                                  }));
                                  setArgumentError(null);
                                }}
                                value={typeof value === "string" ? value : ""}
                              />
                            ) : (
                              <Input
                                aria-describedby={fieldError ? errorId : undefined}
                                aria-invalid={Boolean(fieldError)}
                                className={cn(
                                  "h-12 rounded-md border-border bg-background px-4 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20",
                                  fieldError &&
                                    "!border-red-500 focus-visible:!border-red-600 focus-visible:!ring-red-100"
                                )}
                                id={inputId}
                                onChange={(event) => {
                                  setArgumentValues((current) => ({
                                    ...current,
                                    [input.name]: event.target.value,
                                  }));
                                  setArgumentError(null);
                                }}
                                type={
                                  input.type === "integer" || input.type === "number"
                                    ? "number"
                                    : "text"
                                }
                                value={typeof value === "string" ? value : ""}
                              />
                            )}
                            {fieldError ? (
                              <p
                                aria-live="assertive"
                                className="text-xs font-medium leading-4 text-red-600"
                                id={errorId}
                                role="alert"
                              >
                                {fieldError}
                              </p>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  <details className="group rounded-md border border-border bg-muted/40">
                    <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted">
                      Input schema reference
                    </summary>
                    <pre className="max-h-72 overflow-auto border-t border-border bg-background p-4 text-xs">
                      {JSON.stringify(selectedTool.inputSchema ?? {}, null, 2)}
                    </pre>
                  </details>
                </>
              )}
            </CardContent>
            <div className="flex justify-end border-t border-border bg-muted/30 px-5 py-4">
              <Button
                disabled={isValidating || isLoadingTools || !selectedToolName}
                onClick={validateTool}
                title={validateDisabledReason || "Validate selected tool"}
                type="button"
              >
                <Play className="size-4" />
                {isValidating ? "Validating" : "Validate"}
              </Button>
            </div>
          </Card>

          <Card className="overflow-hidden rounded-md border-border bg-card shadow-none">
            <CardHeader className="border-b border-border px-5 py-4">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                Result
              </CardTitle>
            </CardHeader>
            <CardContent className={result ? "p-6" : "p-10"}>
              {!result ? (
                <div className="flex min-h-40 flex-col items-center justify-center space-y-4 text-center">
                  <div className="flex size-16 items-center justify-center rounded-full border-2 border-dashed border-[var(--outline-variant)] bg-[var(--surface-container)] text-[var(--outline)]">
                    <Terminal className="size-8" />
                  </div>
                  <p className="text-sm leading-5 text-muted-foreground">
                    Run validation to inspect the tool response.
                  </p>
                </div>
              ) : (
                <div
                  aria-atomic="true"
                  aria-live={result.status === "passed" ? "polite" : "assertive"}
                  className={
                    result.status === "passed"
                      ? "rounded-md border border-emerald-200 bg-emerald-50 p-4"
                      : "rounded-md border border-red-200 bg-red-50 p-4"
                  }
                  role={result.status === "passed" ? "status" : "alert"}
                >
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    {result.status === "passed" ? (
                      <CheckCircle2 className="size-4 text-emerald-700" />
                    ) : (
                      <XCircle className="size-4 text-red-700" />
                    )}
                    {result.status === "passed" ? "Validation passed" : "Validation failed"}
                  </div>
                  {result.error ? <div className="mb-3 text-sm">{result.error}</div> : null}
                  <pre className="max-h-96 overflow-auto rounded-md bg-background p-3 text-xs">
                    {JSON.stringify(result.result ?? result, null, 2)}
                  </pre>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
