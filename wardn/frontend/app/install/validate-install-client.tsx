"use client";

import { ApiError, apiRawFetch } from "@/lib/api/client";

import {
  CheckCircle2,
  CircleHelp,
  CircleStop,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Terminal,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { FeedbackMessages } from "@/app/mcp/mcp-list-ui";
import { Badge } from "@/components/ui/badge";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
};

const mcpToolDiscoveryTimeoutMs = 120_000;

function caughtMessage(caught: unknown, fallback: string) {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

function runtimeStatusLabel(status: string | undefined) {
  if (!status) {
    return "Not started";
  }
  return status.replace(/_/g, " ");
}

function runtimeStatusBadgeVariant(
  status: string | undefined
): "success" | "secondary" | "destructive" | "outline" {
  if (status === "idle" || status === "running" || status === "ready") {
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

function runtimePolicyDetails(installation: MCPServerInstallationRead) {
  if (installation.runtimeProvider !== "kubernetes") {
    return [];
  }
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const rawPolicy = runtimeConfig.networkPolicy;
  if (!isRecord(rawPolicy)) {
    return ["Default-deny egress", "Remote MCP endpoint egress"];
  }
  const denyOtherEgress = rawPolicy.denyOtherEgress ?? rawPolicy.isolationEnabled;
  if (denyOtherEgress === false) {
    return ["Default-deny egress off"];
  }
  const details = ["Default-deny egress"];
  if (rawPolicy.allowRemoteMcpEgress !== false) {
    details.push("Remote MCP endpoint egress");
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
  installation: MCPServerInstallationRead;
  organizationId: string;
  workspaceId: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
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
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshNotice, setRefreshNotice] = useState("");
  const [isLoadingTools, setIsLoadingTools] = useState(true);
  const [isLoadingRuntime, setIsLoadingRuntime] = useState(true);
  const [isValidating, setIsValidating] = useState(false);
  const [runtimeAction, setRuntimeAction] = useState<RuntimeAction | null>(null);

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
    const { reportError = true } = options;
    try {
      const data = await fetchRuntimeState();
      setRuntimeState(data);
      return true;
    } catch (caught) {
      if (reportError) {
        setError(caughtMessage(caught, "Runtime state could not be loaded."));
      }
      return false;
    } finally {
      setIsLoadingRuntime(false);
    }
  }, [fetchRuntimeState]);

  const loadTools = useCallback(async (options: RefreshOptions = {}) => {
    const { reportError = true } = options;
    try {
      applyLoadedTools(await fetchTools());
      return true;
    } catch (caught) {
      if (reportError) {
        setError(caughtMessage(caught, "Tools could not be loaded."));
      }
      return false;
    } finally {
      setIsLoadingTools(false);
    }
  }, [applyLoadedTools, fetchTools]);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialRuntimeState() {
      try {
        const data = await fetchRuntimeState();
        if (!cancelled) {
          setRuntimeState(data);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(
            caught instanceof Error ? caught.message : "Runtime state could not be loaded."
          );
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
  }, [fetchRuntimeState]);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialTools() {
      try {
        const nextTools = await fetchTools();
        if (!cancelled) {
          applyLoadedTools(nextTools);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Tools could not be loaded.");
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
    setError("");
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
        const toolsRefreshed = await loadTools({ reportError: false });
        if (!toolsRefreshed) {
          setRefreshNotice(
            "Runtime control succeeded, but tools are still not ready to refresh. Try again in a few seconds."
          );
        }
      }
      const runtimeRefreshed = await loadRuntimeState({ reportError: false });
      if (!runtimeRefreshed) {
        setRefreshNotice(
          "Runtime control succeeded, but the latest runtime state could not refresh. Try again in a few seconds."
        );
      }
    } catch (caught) {
      setError(
        caughtMessage(caught, `Runtime could not be ${runtimeActionLabels[action]}.`)
      );
    } finally {
      setRuntimeAction(null);
    }
  }

  async function validateTool() {
    const toolName = selectedToolName.trim();
    if (!toolName) {
      setError("Tool name is required.");
      return;
    }

    const requiredError = validateRequiredArguments(selectedInputs, argumentValues);
    if (requiredError) {
      setArgumentError(requiredError);
      return;
    }

    setIsValidating(true);
    setError("");
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
      setError(caught instanceof Error ? caught.message : "Tool validation failed.");
    } finally {
      setIsValidating(false);
    }
  }

  const runtimeStatus = runtimeSession?.status;
  const runtimeHealth = runtimeState?.health ?? null;
  const runtimeDisplayStatus = runtimeHealth?.status || runtimeStatus;
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
  const canStartRuntime = Boolean(runtimeState?.canStart) && !runtimeBusy;
  const canStopRuntime = Boolean(runtimeState?.canStop) && !runtimeBusy;
  const canRestartRuntime = Boolean(runtimeState?.canRestart) && !runtimeBusy;
  const canRedeployRuntime = Boolean(runtimeState?.canRedeploy) && !runtimeBusy;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <Card className="h-32 rounded-xl border-[var(--outline-variant)] bg-white shadow-none transition-shadow hover:shadow-sm">
          <CardContent className="flex h-full flex-col justify-between p-5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Server
            </span>
            <div>
              <h3 className="truncate text-xl font-bold leading-7 text-[var(--on-surface)]">
                {installation.server.title || installation.serverName}
              </h3>
            </div>
          </CardContent>
        </Card>
        <Card className="h-32 rounded-xl border-[var(--outline-variant)] bg-white shadow-none transition-shadow hover:shadow-sm">
          <CardContent className="flex h-full flex-col justify-between p-5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Instance
            </span>
            <div>
              <h3 className="truncate text-xl font-bold leading-7 text-[var(--on-surface)]">
                {installation.configName}
              </h3>
            </div>
          </CardContent>
        </Card>
        <Card className="h-32 rounded-xl border-[var(--outline-variant)] bg-white shadow-none transition-shadow hover:shadow-sm">
          <CardContent className="flex h-full flex-col justify-between p-5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Version
            </span>
            <div>
              <h3 className="truncate text-xl font-bold leading-7 text-[var(--on-surface)]">
                {installation.installedVersion}
              </h3>
              <p className="mt-1 text-sm leading-5 text-[var(--on-surface-variant)]">
                {installation.installType}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
        <CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 space-y-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Runtime
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={
                  isLoadingRuntime
                    ? "outline"
                    : runtimeStatusBadgeVariant(runtimeDisplayStatus)
                }
              >
                {isLoadingRuntime ? "Loading" : runtimeStatusLabel(runtimeDisplayStatus)}
              </Badge>
              {runtimeSession?.runtimeProvider ? (
                <span className="text-sm text-[var(--on-surface-variant)]">
                  {runtimeSession.runtimeProvider}
                </span>
              ) : null}
            </div>
            {runtimeDetails.length > 0 ? (
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--on-surface-variant)]">
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
            {runtimeHealth?.message ? (
              <p className="max-w-3xl text-xs leading-5 text-[var(--on-surface-variant)]">
                {runtimeHealth.message}
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

      <FeedbackMessages error={error} notice={notice} />
      {refreshNotice ? (
        <AsyncFeedback className="mb-4 rounded-lg px-4 py-3" variant="info">
          {refreshNotice}
        </AsyncFeedback>
      ) : null}

      <div className="grid grid-cols-12 items-start gap-6">
        <Card className="col-span-12 max-h-[600px] overflow-hidden rounded-xl border-[var(--outline-variant)] bg-white shadow-none lg:col-span-3">
          <CardHeader className="border-b border-[var(--outline-variant)] p-4">
            <CardTitle className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Tools
            </CardTitle>
            <div className="relative mt-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--outline)]" />
              <Input
                className="h-10 rounded-lg border-[var(--outline-variant)] bg-[var(--surface)] pl-10 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20"
                onChange={(event) => setToolSearch(event.target.value)}
                placeholder="Search tools"
                value={toolSearch}
              />
            </div>
          </CardHeader>
          <CardContent className="max-h-[508px] overflow-y-auto px-0 pb-4 pt-0">
            {isLoadingTools ? (
              <div className="p-4 text-sm text-[var(--on-surface-variant)]">
                Loading tools from the installed server...
              </div>
            ) : tools.length === 0 ? (
              <div className="p-4 text-sm text-[var(--on-surface-variant)]">
                No tools were discovered for this server.
              </div>
            ) : filteredTools.length === 0 ? (
              <div className="p-4 text-sm text-[var(--on-surface-variant)]">
                No tools match this search.
              </div>
            ) : (
              <div className="divide-y divide-[var(--outline-variant)]/30">
                {filteredTools.map((tool) => (
                  <button
                    className={
                      tool.toolName === selectedToolName
                        ? "block w-full border-l-4 border-primary bg-[var(--secondary-container)]/50 px-4 py-4 text-left"
                        : "block w-full border-l-4 border-transparent px-4 py-4 text-left transition-colors hover:bg-[var(--surface-container)]"
                    }
                    key={tool.toolName}
                    onClick={() => selectTool(tool)}
                    type="button"
                  >
                    <span className="block truncate text-sm font-semibold leading-5 text-[var(--on-surface)]">
                      {tool.title || tool.toolName}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="col-span-12 space-y-6 lg:col-span-9">
          <Card className="overflow-hidden rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
            <CardHeader className="border-b border-[var(--outline-variant)] p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-2xl font-bold leading-8 tracking-normal text-[var(--on-surface)]">
                    {selectedTool?.title || selectedTool?.toolName || "Select a tool"}
                  </CardTitle>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-6 p-6">
              {!selectedTool ? (
                <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed border-[var(--outline-variant)] text-sm text-[var(--on-surface-variant)]">
                  Select a tool to configure validation arguments.
                </div>
              ) : (
                <>
                  {selectedTool.description ? (
                    <div className="space-y-3">
                      <p className="whitespace-pre-wrap text-sm leading-5 text-[var(--on-surface)]/80">
                        {selectedTool.description}
                      </p>
                    </div>
                  ) : null}

                  {selectedInputs.length === 0 ? (
                    <div className="rounded-lg border border-[var(--outline-variant)]/40 bg-[var(--surface)] p-4 text-sm text-[var(--on-surface-variant)]">
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
                                  className="text-xs font-semibold leading-4 text-[var(--on-surface)]"
                                  htmlFor={inputId}
                                >
                                  {input.name}
                                  {input.required ? <span className="text-red-600"> *</span> : null}
                                </label>
                                {input.description ? (
                                  <span
                                    aria-label={`${input.name} help`}
                                    className="inline-flex text-[var(--on-surface-variant)]"
                                    title={input.description}
                                  >
                                    <CircleHelp className="size-4" />
                                  </span>
                                ) : null}
                              </div>
                              <span className="rounded border border-[var(--outline-variant)] bg-[var(--surface)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--on-surface-variant)]">
                                {input.type}
                              </span>
                            </div>

                            {input.type === "boolean" ? (
                              <label
                                className={cn(
                                  "flex h-11 items-center gap-2 rounded-lg border border-[var(--outline-variant)] bg-white px-4 text-sm",
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
                                    "h-12 rounded-lg border-[var(--outline-variant)] bg-white px-4 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20",
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
                                  "min-h-32 w-full rounded-lg border border-[var(--outline-variant)] bg-white px-4 py-3 font-mono text-sm outline-none transition-all focus:border-primary focus:ring-1 focus:ring-primary/20",
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
                                  "h-12 rounded-lg border-[var(--outline-variant)] bg-white px-4 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20",
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

                  <details className="group rounded-lg border border-[var(--outline-variant)]/30 bg-[var(--surface)]">
                    <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-[var(--on-surface-variant)] transition-colors hover:bg-[var(--surface-container)]">
                      Input schema reference
                    </summary>
                    <pre className="max-h-72 overflow-auto border-t border-[var(--outline-variant)]/30 bg-white p-4 text-xs">
                      {JSON.stringify(selectedTool.inputSchema ?? {}, null, 2)}
                    </pre>
                  </details>
                </>
              )}
            </CardContent>
            <div className="flex justify-end border-t border-[var(--outline-variant)] bg-[var(--surface)] px-6 py-4">
              <Button
                disabled={isValidating || isLoadingTools || !selectedToolName}
                onClick={validateTool}
                type="button"
              >
                <Play className="size-4" />
                {isValidating ? "Validating" : "Validate"}
              </Button>
            </div>
          </Card>

          <Card className="overflow-hidden rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
            <CardHeader className="border-b border-[var(--outline-variant)] px-6 py-4">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
                Result
              </CardTitle>
            </CardHeader>
            <CardContent className={result ? "p-6" : "p-10"}>
              {!result ? (
                <div className="flex min-h-40 flex-col items-center justify-center space-y-4 text-center">
                  <div className="flex size-16 items-center justify-center rounded-full border-2 border-dashed border-[var(--outline-variant)] bg-[var(--surface-container)] text-[var(--outline)]">
                    <Terminal className="size-8" />
                  </div>
                  <p className="text-sm leading-5 text-[var(--on-surface-variant)]">
                    Run validation to inspect the tool response.
                  </p>
                </div>
              ) : (
                <div
                  aria-atomic="true"
                  aria-live={result.status === "passed" ? "polite" : "assertive"}
                  className={
                    result.status === "passed"
                      ? "rounded-lg border border-emerald-200 bg-emerald-50 p-4"
                      : "rounded-lg border border-red-200 bg-red-50 p-4"
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
