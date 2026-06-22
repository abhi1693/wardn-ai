"use client";

import {
  CheckCircle2,
  CircleHelp,
  Edit2,
  Package,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
  MCPServerInstallationToolsResponse,
  MCPServerInstallationToolValidationResponse,
  MCPServerToolRead,
} from "@/lib/api/generated/model";

type InstalledListClientProps = {
  initialInstallations: MCPServerInstallationRead[];
};

type ToolInputProperty = {
  name: string;
  required: boolean;
  type: string;
  description: string;
  enumValues: string[];
  schema: Record<string, unknown>;
};

type ValidationArgumentValue = string | boolean;

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

function detailServerUrl(serverName: string, version: string) {
  return `/registry/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function editInstallUrl(installationId: string) {
  return `/install/${encodeURIComponent(installationId)}/edit`;
}

function runtimeLabel(installation: MCPServerInstallationRead) {
  const normalized = installation.installType.toLowerCase();
  if (normalized === "remote") {
    return "Remote endpoint";
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
  return installation.installType;
}

function serverIconUrl(installation: MCPServerInstallationRead) {
  const icon = installation.server.icons?.find((item) => {
    const source = (item as Record<string, unknown>).src;
    return typeof source === "string" && source.trim();
  }) as Record<string, unknown> | undefined;
  const source = icon?.src;
  return typeof source === "string" ? source : "";
}

function validationEndpoint(installationId: string) {
  return `/api/mcp/registry/installed-server-configs/${encodeURIComponent(
    installationId
  )}/validate-tool`;
}

function toolsEndpoint(installationId: string) {
  return `/api/mcp/registry/installed-server-configs/${encodeURIComponent(installationId)}/tools`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function schemaType(schema: Record<string, unknown>) {
  const rawType = schema.type;
  if (Array.isArray(rawType)) {
    return rawType.find((item) => typeof item === "string") ?? "object";
  }
  return typeof rawType === "string" ? rawType : "object";
}

function exampleValueForSchema(schema: unknown, depth = 0): unknown {
  if (!isRecord(schema) || depth > 3) {
    return "";
  }

  const type = schemaType(schema);
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
    return argumentsTemplateForSchema(schema, depth + 1);
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
    return {
      name,
      required: requiredNames.has(name),
      type: schemaType(property),
      description: typeof property.description === "string" ? property.description : "",
      enumValues: Array.isArray(property.enum)
        ? property.enum.filter((item): item is string => typeof item === "string")
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
      result[input.name] = JSON.stringify(example, null, 2);
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
): { argumentsValue: Record<string, unknown>; error: string } {
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
        return { argumentsValue: {}, error: `Required argument missing: ${input.name}` };
      }
      continue;
    }

    if (input.type === "integer" || input.type === "number") {
      const parsed = Number(value);
      if (!Number.isFinite(parsed) || (input.type === "integer" && !Number.isInteger(parsed))) {
        return { argumentsValue: {}, error: `${input.name} must be a valid ${input.type}.` };
      }
      argumentsValue[input.name] = parsed;
      continue;
    }

    if (input.type === "object" || input.type === "array") {
      try {
        const parsed = JSON.parse(value) as unknown;
        if (input.type === "object" && (!isRecord(parsed) || Array.isArray(parsed))) {
          return { argumentsValue: {}, error: `${input.name} must be a JSON object.` };
        }
        if (input.type === "array" && !Array.isArray(parsed)) {
          return { argumentsValue: {}, error: `${input.name} must be a JSON array.` };
        }
        argumentsValue[input.name] = parsed;
      } catch {
        return { argumentsValue: {}, error: `${input.name} must contain valid JSON.` };
      }
      continue;
    }

    argumentsValue[input.name] = value;
  }

  return { argumentsValue, error: "" };
}

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function loadToolsFromGateway(
  installation: MCPServerInstallationRead
): Promise<MCPServerToolRead[]> {
  const tools: MCPServerToolRead[] = [];
  let cursor = "";
  let requestId = 1;

  do {
    const response = await fetch("/api/mcp/gateway", {
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
    });

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

export function InstalledListClient({ initialInstallations }: InstalledListClientProps) {
  const [installations, setInstallations] =
    useState<MCPServerInstallationRead[]>(initialInstallations);
  const [isLoading, setIsLoading] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [toolLoadError, setToolLoadError] = useState("");
  const [toolSearch, setToolSearch] = useState("");
  const [validationArgumentError, setValidationArgumentError] = useState("");
  const [validationInstallation, setValidationInstallation] =
    useState<MCPServerInstallationRead | null>(null);
  const [validationToolName, setValidationToolName] = useState("");
  const [validationArgumentValues, setValidationArgumentValues] = useState<
    Record<string, ValidationArgumentValue>
  >({});
  const [validationTools, setValidationTools] = useState<MCPServerToolRead[]>([]);
  const [validationResult, setValidationResult] =
    useState<MCPServerInstallationToolValidationResponse | null>(null);

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

  const selectedValidationTool = useMemo(
    () => validationTools.find((tool) => tool.toolName === validationToolName) ?? null,
    [validationToolName, validationTools]
  );
  const selectedValidationToolInputs = useMemo(
    () => inputProperties(selectedValidationTool?.inputSchema),
    [selectedValidationTool]
  );
  const filteredValidationTools = useMemo(() => {
    const query = toolSearch.trim().toLocaleLowerCase();
    if (!query) {
      return validationTools;
    }
    return validationTools.filter((tool) =>
      [tool.title, tool.toolName, tool.description]
        .filter(Boolean)
        .some((value) => value.toLocaleLowerCase().includes(query))
    );
  }, [toolSearch, validationTools]);

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

  async function removeInstallation(installation: MCPServerInstallationRead) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        `/api/mcp/registry/installed-server-configs/${encodeURIComponent(installation.id)}`,
        { method: "DELETE" }
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

  function selectValidationTool(tool: MCPServerToolRead) {
    setValidationToolName(tool.toolName);
    setValidationArgumentValues(initialArgumentValuesForSchema(tool.inputSchema));
    setValidationResult(null);
    setValidationArgumentError("");
  }

  async function openValidation(installation: MCPServerInstallationRead) {
    setValidationInstallation(installation);
    setValidationToolName("");
    setValidationArgumentValues({});
    setValidationTools([]);
    setToolSearch("");
    setValidationResult(null);
    setValidationArgumentError("");
    setError("");
    setNotice("");
    setToolLoadError("");

    setIsLoadingTools(true);
    try {
      const response = await fetch(toolsEndpoint(installation.id), {
        cache: "no-store",
      });
      if (!response.ok) {
        if (response.status === 404) {
          const fallbackTools = await loadToolsFromGateway(installation);
          setValidationTools(
            fallbackTools.sort((left, right) => left.toolName.localeCompare(right.toolName))
          );
          if (fallbackTools.length === 1) {
            selectValidationTool(fallbackTools[0]);
          }
          return;
        }
        throw new Error(await responseErrorMessage(response, "Tools could not be loaded."));
      }
      const data = (await response.json()) as MCPServerInstallationToolsResponse;
      const tools = [...data.tools].sort((left, right) => left.toolName.localeCompare(right.toolName));
      setValidationTools(tools);
      if (tools.length === 1) {
        selectValidationTool(tools[0]);
      }
    } catch (caught) {
      setToolLoadError(caught instanceof Error ? caught.message : "Tools could not be loaded.");
    } finally {
      setIsLoadingTools(false);
    }
  }

  async function validateInstallation() {
    if (!validationInstallation) {
      return;
    }
    const toolName = validationToolName.trim();
    if (!toolName) {
      setError("Tool name is required.");
      return;
    }

    const parsedArguments = parseArgumentsFromFields(
      selectedValidationToolInputs,
      validationArgumentValues
    );
    if (parsedArguments.error) {
      setValidationArgumentError(parsedArguments.error);
      return;
    }

    setIsValidating(true);
    setError("");
    setValidationArgumentError("");
    setNotice("");
    setValidationResult(null);
    try {
      const response = await fetch(validationEndpoint(validationInstallation.id), {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          toolName,
          arguments: parsedArguments.argumentsValue,
        }),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Tool validation failed."));
      }
      const data = (await response.json()) as MCPServerInstallationToolValidationResponse;
      setValidationResult(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Tool validation failed.");
    } finally {
      setIsValidating(false);
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
              <Button asChild disabled={isMutating}>
                <Link href="/install/new">
                  <Plus className="size-4" />
                  Add
                </Link>
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
                sortedInstallations.map((installation) => {
                  const iconUrl = serverIconUrl(installation);

                  return (
                    <TableRow key={installation.id}>
                      <TableCell>
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted">
                            {iconUrl ? (
                              <span
                                aria-hidden="true"
                                className="size-5 bg-contain bg-center bg-no-repeat"
                                style={{ backgroundImage: `url("${iconUrl}")` }}
                              />
                            ) : (
                              <Package className="size-4 text-muted-foreground" />
                            )}
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
                        <div className="font-medium">{installation.configName}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="font-normal">
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
                        <div className="flex justify-end gap-2">
                          <Button asChild disabled={isMutating} size="icon" type="button" variant="outline">
                            <Link aria-label={`Edit ${installation.configName}`} href={editInstallUrl(installation.id)}>
                              <Edit2 className="size-4" />
                            </Link>
                          </Button>
                          <Button
                            disabled={isMutating || isValidating}
                            onClick={() => void openValidation(installation)}
                            aria-label={`Validate ${installation.configName}`}
                            size="icon"
                            type="button"
                            variant="outline"
                          >
                            <Play className="size-4" />
                          </Button>
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
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {validationInstallation ? (
        <Card>
          <CardContent className="space-y-4 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Validate tool execution</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {validationInstallation.server.title || validationInstallation.serverName} /{" "}
                  {validationInstallation.configName}
                </div>
              </div>
              <Button
                onClick={() => {
                  setValidationInstallation(null);
                  setValidationTools([]);
                  setValidationToolName("");
                  setToolSearch("");
                  setValidationArgumentValues({});
                  setValidationResult(null);
                }}
                type="button"
                variant="outline"
              >
                Close
              </Button>
            </div>

            <div className="grid gap-4 lg:grid-cols-[minmax(260px,360px)_minmax(0,1fr)]">
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">Tools</div>
                  {validationTools.length > 0 ? (
                    <div className="text-xs text-muted-foreground">
                      {filteredValidationTools.length} of {validationTools.length}
                    </div>
                  ) : null}
                </div>
                {isLoadingTools ? (
                  <div className="rounded-md border p-4 text-sm text-muted-foreground">
                    Loading tools from the installed server...
                  </div>
                ) : toolLoadError ? (
                  <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                    {toolLoadError}
                  </div>
                ) : validationTools.length === 0 ? (
                  <div className="rounded-md border p-4 text-sm text-muted-foreground">
                    No tools were discovered for this server.
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Input
                      aria-label="Search tools"
                      onChange={(event) => setToolSearch(event.target.value)}
                      placeholder="Search tools"
                      value={toolSearch}
                    />
                    <div className="max-h-96 overflow-auto rounded-md border">
                      {filteredValidationTools.length === 0 ? (
                        <div className="p-4 text-sm text-muted-foreground">
                          No tools match this search.
                        </div>
                      ) : (
                        filteredValidationTools.map((tool) => (
                          <button
                            className={
                              tool.toolName === validationToolName
                                ? "block w-full border-b bg-accent px-3 py-2 text-left last:border-b-0"
                                : "block w-full border-b px-3 py-2 text-left last:border-b-0 hover:bg-muted"
                            }
                            key={tool.toolName}
                            onClick={() => selectValidationTool(tool)}
                            type="button"
                          >
                            <div className="text-sm font-medium">
                              {tool.title || tool.toolName}
                            </div>
                            <div className="mt-0.5 break-all text-xs text-muted-foreground">
                              {tool.toolName}
                            </div>
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>

              {selectedValidationTool ? (
                <div className="space-y-4">
                  <div className="rounded-md border bg-muted/20 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium">
                          {selectedValidationTool.title || selectedValidationTool.toolName}
                        </div>
                        <div className="mt-0.5 break-all text-xs text-muted-foreground">
                          {selectedValidationTool.toolName}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2 text-xs">
                        <Badge variant="outline">
                          {selectedValidationToolInputs.length} inputs
                        </Badge>
                        <Badge variant="outline">
                          {selectedValidationToolInputs.filter((input) => input.required).length} required
                        </Badge>
                      </div>
                    </div>
                    {selectedValidationTool.description ? (
                      <div className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
                        {selectedValidationTool.description}
                      </div>
                    ) : null}
                  </div>

                  <div className="space-y-3">
                    <div className="text-sm font-medium">Arguments</div>
                    {selectedValidationToolInputs.length === 0 ? (
                      <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
                        This tool does not declare input fields.
                      </div>
                    ) : (
                      <div className="grid gap-3 md:grid-cols-2">
                        {selectedValidationToolInputs.map((input) => {
                          const inputId = `validation-argument-${input.name}`;
                          const value = validationArgumentValues[input.name];

                          return (
                            <div className="space-y-2" key={input.name}>
                              <div className="flex min-h-6 items-center gap-2">
                                <label className="text-sm font-medium" htmlFor={inputId}>
                                  {input.name}
                                  {input.required ? <span className="text-red-600"> *</span> : null}
                                </label>
                                {input.description ? (
                                  <span className="group relative inline-flex">
                                    <button
                                      aria-label={`${input.name} help`}
                                      className="inline-flex text-muted-foreground outline-none hover:text-foreground focus-visible:text-foreground"
                                      type="button"
                                    >
                                      <CircleHelp className="size-4" />
                                    </button>
                                    <span className="pointer-events-none absolute left-1/2 top-6 z-50 hidden w-80 -translate-x-1/2 rounded-md border bg-popover px-3 py-2 text-xs font-normal leading-5 text-popover-foreground shadow-md group-hover:block group-focus-within:block">
                                      {input.description}
                                    </span>
                                  </span>
                                ) : null}
                                <Badge className="ml-auto" variant="outline">
                                  {input.type}
                                </Badge>
                              </div>

                              {input.type === "boolean" ? (
                                <label className="flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm">
                                  <input
                                    checked={value === true}
                                    id={inputId}
                                    onChange={(event) => {
                                      setValidationArgumentValues((current) => ({
                                        ...current,
                                        [input.name]: event.target.checked,
                                      }));
                                      setValidationArgumentError("");
                                    }}
                                    type="checkbox"
                                  />
                                  Enabled
                                </label>
                              ) : input.enumValues.length > 0 ? (
                                <select
                                  className="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                  id={inputId}
                                  onChange={(event) => {
                                    setValidationArgumentValues((current) => ({
                                      ...current,
                                      [input.name]: event.target.value,
                                    }));
                                    setValidationArgumentError("");
                                  }}
                                  value={typeof value === "string" ? value : ""}
                                >
                                  {input.enumValues.map((option) => (
                                    <option key={option} value={option}>
                                      {option}
                                    </option>
                                  ))}
                                </select>
                              ) : input.type === "object" || input.type === "array" ? (
                                <textarea
                                  className="min-h-28 w-full rounded-md border bg-background px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                  id={inputId}
                                  onChange={(event) => {
                                    setValidationArgumentValues((current) => ({
                                      ...current,
                                      [input.name]: event.target.value,
                                    }));
                                    setValidationArgumentError("");
                                  }}
                                  value={typeof value === "string" ? value : ""}
                                />
                              ) : (
                                <Input
                                  id={inputId}
                                  onChange={(event) => {
                                    setValidationArgumentValues((current) => ({
                                      ...current,
                                      [input.name]: event.target.value,
                                    }));
                                    setValidationArgumentError("");
                                  }}
                                  type={
                                    input.type === "integer" || input.type === "number"
                                      ? "number"
                                      : "text"
                                  }
                                  value={typeof value === "string" ? value : ""}
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {validationArgumentError ? (
                      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                        {validationArgumentError}
                      </div>
                    ) : null}
                  </div>

                  <details className="rounded-md border bg-muted/20">
                    <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
                      Input schema reference
                    </summary>
                    <pre className="max-h-72 overflow-auto border-t bg-background p-3 text-xs">
                      {JSON.stringify(selectedValidationTool.inputSchema ?? {}, null, 2)}
                    </pre>
                  </details>
                </div>
              ) : (
                <div className="flex min-h-48 items-center justify-center rounded-md border text-sm text-muted-foreground">
                  Select a tool to validate
                </div>
              )}
            </div>

            <div className="flex justify-end">
              <Button
                disabled={isValidating || isLoadingTools || !validationToolName}
                onClick={validateInstallation}
                type="button"
              >
                <Play className="size-4" />
                {isValidating ? "Validating" : "Validate"}
              </Button>
            </div>

            {validationResult ? (
              <div
                className={
                  validationResult.status === "passed"
                    ? "rounded-md border border-emerald-200 bg-emerald-50 p-3"
                    : "rounded-md border border-red-200 bg-red-50 p-3"
                }
              >
                <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                  {validationResult.status === "passed" ? (
                    <CheckCircle2 className="size-4 text-emerald-700" />
                  ) : (
                    <XCircle className="size-4 text-red-700" />
                  )}
                  {validationResult.status === "passed" ? "Validation passed" : "Validation failed"}
                </div>
                {validationResult.error ? (
                  <div className="mb-2 text-sm">{validationResult.error}</div>
                ) : null}
                <pre className="max-h-72 overflow-auto rounded-md bg-background p-3 text-xs">
                  {JSON.stringify(validationResult.result ?? validationResult, null, 2)}
                </pre>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
