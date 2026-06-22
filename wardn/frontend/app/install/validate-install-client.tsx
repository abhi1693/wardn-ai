"use client";

import {
  CheckCircle2,
  CircleHelp,
  Play,
  Search,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { FeedbackMessages, responseErrorMessage } from "@/app/mcp/mcp-list-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type {
  MCPServerInstallationRead,
  MCPServerInstallationToolsResponse,
  MCPServerInstallationToolValidationResponse,
  MCPServerToolRead,
} from "@/lib/api/generated/model";

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

type ValidateInstallClientProps = {
  installation: MCPServerInstallationRead;
};

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

export function ValidateInstallClient({ installation }: ValidateInstallClientProps) {
  const [tools, setTools] = useState<MCPServerToolRead[]>([]);
  const [toolSearch, setToolSearch] = useState("");
  const [selectedToolName, setSelectedToolName] = useState("");
  const [argumentValues, setArgumentValues] = useState<Record<string, ValidationArgumentValue>>({});
  const [argumentError, setArgumentError] = useState("");
  const [result, setResult] = useState<MCPServerInstallationToolValidationResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoadingTools, setIsLoadingTools] = useState(true);
  const [isValidating, setIsValidating] = useState(false);

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
    setArgumentError("");
    setResult(null);
  }

  useEffect(() => {
    let cancelled = false;

    async function loadTools() {
      setIsLoadingTools(true);
      setError("");
      try {
        const response = await fetch(toolsEndpoint(installation.id), {
          cache: "no-store",
        });
        if (!response.ok) {
          if (response.status === 404) {
            const fallbackTools = await loadToolsFromGateway(installation);
            const sortedFallbackTools = fallbackTools.sort((left, right) =>
              left.toolName.localeCompare(right.toolName)
            );
            if (!cancelled) {
              setTools(sortedFallbackTools);
              if (sortedFallbackTools.length > 0) {
                selectTool(sortedFallbackTools[0]);
              }
            }
            return;
          }
          throw new Error(await responseErrorMessage(response, "Tools could not be loaded."));
        }
        const data = (await response.json()) as MCPServerInstallationToolsResponse;
        const sortedTools = [...data.tools].sort((left, right) =>
          left.toolName.localeCompare(right.toolName)
        );
        if (!cancelled) {
          setTools(sortedTools);
          if (sortedTools.length > 0) {
            selectTool(sortedTools[0]);
          }
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

    void loadTools();

    return () => {
      cancelled = true;
    };
  }, [installation]);

  async function validateTool() {
    const toolName = selectedToolName.trim();
    if (!toolName) {
      setError("Tool name is required.");
      return;
    }

    const parsedArguments = parseArgumentsFromFields(selectedInputs, argumentValues);
    if (parsedArguments.error) {
      setArgumentError(parsedArguments.error);
      return;
    }

    setIsValidating(true);
    setError("");
    setArgumentError("");
    setResult(null);
    try {
      const response = await fetch(validationEndpoint(installation.id), {
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
      setResult(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Tool validation failed.");
    } finally {
      setIsValidating(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
          <CardContent className="p-4">
            <div className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Server
            </div>
            <div className="mt-2 truncate text-lg font-semibold">
              {installation.server.title || installation.serverName}
            </div>
            <div className="mt-1 break-all text-xs text-[var(--on-surface-variant)]">
              {installation.serverName}
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
          <CardContent className="p-4">
            <div className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Instance
            </div>
            <div className="mt-2 truncate text-lg font-semibold">{installation.configName}</div>
            <div className="mt-1 text-xs text-[var(--on-surface-variant)]">
              {installation.status}
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
          <CardContent className="p-4">
            <div className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--on-surface-variant)]">
              Version
            </div>
            <div className="mt-2 truncate text-lg font-semibold">
              {installation.installedVersion}
            </div>
            <div className="mt-1 text-xs text-[var(--on-surface-variant)]">
              {installation.installType}
            </div>
          </CardContent>
        </Card>
      </div>

      <FeedbackMessages error={error} />

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
          <CardHeader>
            <CardTitle>Tools</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--on-surface-variant)]" />
              <Input
                className="pl-9"
                onChange={(event) => setToolSearch(event.target.value)}
                placeholder="Search tools"
                value={toolSearch}
              />
            </div>
            <div className="max-h-[520px] overflow-auto rounded-lg border border-[var(--outline-variant)]">
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
                filteredTools.map((tool) => (
                  <button
                    className={
                      tool.toolName === selectedToolName
                        ? "block w-full border-b border-[var(--outline-variant)] bg-[var(--surface-container-low)] px-3 py-3 text-left last:border-b-0"
                        : "block w-full border-b border-[var(--outline-variant)] px-3 py-3 text-left transition-colors last:border-b-0 hover:bg-[var(--surface-container-low)]"
                    }
                    key={tool.toolName}
                    onClick={() => selectTool(tool)}
                    type="button"
                  >
                    <div className="text-sm font-semibold">{tool.title || tool.toolName}</div>
                    <div className="mt-0.5 break-all text-xs text-[var(--on-surface-variant)]">
                      {tool.toolName}
                    </div>
                  </button>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>{selectedTool?.title || selectedTool?.toolName || "Select a tool"}</CardTitle>
                  {selectedTool ? (
                    <div className="mt-1 break-all text-xs text-[var(--on-surface-variant)]">
                      {selectedTool.toolName}
                    </div>
                  ) : null}
                </div>
                {selectedTool ? (
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">{selectedInputs.length} inputs</Badge>
                    <Badge variant="outline">
                      {selectedInputs.filter((input) => input.required).length} required
                    </Badge>
                  </div>
                ) : null}
              </div>
              {selectedTool?.description ? (
                <p className="mt-2 whitespace-pre-wrap text-sm leading-5 text-[var(--on-surface-variant)]">
                  {selectedTool.description}
                </p>
              ) : null}
            </CardHeader>
            <CardContent className="space-y-4">
              {!selectedTool ? (
                <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed border-[var(--outline-variant)] text-sm text-[var(--on-surface-variant)]">
                  Select a tool to configure validation arguments.
                </div>
              ) : selectedInputs.length === 0 ? (
                <div className="rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4 text-sm text-[var(--on-surface-variant)]">
                  This tool does not declare input fields.
                </div>
              ) : (
                <div className="grid gap-4 md:grid-cols-2">
                  {selectedInputs.map((input) => {
                    const inputId = `validation-argument-${input.name}`;
                    const value = argumentValues[input.name];

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
                                className="inline-flex text-[var(--on-surface-variant)] outline-none hover:text-[var(--on-surface)] focus-visible:text-[var(--on-surface)]"
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
                                setArgumentValues((current) => ({
                                  ...current,
                                  [input.name]: event.target.checked,
                                }));
                                setArgumentError("");
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
                              setArgumentError("");
                            }}
                            value={typeof value === "string" ? value : ""}
                          >
                            <SelectTrigger
                              className="h-9 rounded-lg border-[var(--outline-variant)] bg-white shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20"
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
                            className="min-h-28 w-full rounded-md border bg-background px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            id={inputId}
                            onChange={(event) => {
                              setArgumentValues((current) => ({
                                ...current,
                                [input.name]: event.target.value,
                              }));
                              setArgumentError("");
                            }}
                            value={typeof value === "string" ? value : ""}
                          />
                        ) : (
                          <Input
                            id={inputId}
                            onChange={(event) => {
                              setArgumentValues((current) => ({
                                ...current,
                                [input.name]: event.target.value,
                              }));
                              setArgumentError("");
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

              {argumentError ? (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {argumentError}
                </div>
              ) : null}

              {selectedTool ? (
                <details className="rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)]">
                  <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
                    Input schema reference
                  </summary>
                  <pre className="max-h-72 overflow-auto border-t bg-background p-3 text-xs">
                    {JSON.stringify(selectedTool.inputSchema ?? {}, null, 2)}
                  </pre>
                </details>
              ) : null}

              <div className="flex justify-end">
                <Button
                  disabled={isValidating || isLoadingTools || !selectedToolName}
                  onClick={validateTool}
                  type="button"
                >
                  <Play className="size-4" />
                  {isValidating ? "Validating" : "Validate"}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
            <CardHeader>
              <CardTitle>Result</CardTitle>
            </CardHeader>
            <CardContent>
              {!result ? (
                <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed border-[var(--outline-variant)] text-sm text-[var(--on-surface-variant)]">
                  Run validation to inspect the tool response.
                </div>
              ) : (
                <div
                  className={
                    result.status === "passed"
                      ? "rounded-lg border border-emerald-200 bg-emerald-50 p-4"
                      : "rounded-lg border border-red-200 bg-red-50 p-4"
                  }
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
