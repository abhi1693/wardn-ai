"use client";

import {
  CheckCircle2,
  CircleHelp,
  Play,
  Search,
  Terminal,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { FeedbackMessages, responseErrorMessage } from "@/app/mcp/mcp-list-ui";
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

type ArgumentFieldError = {
  field: string;
  message: string;
};

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
  const [argumentError, setArgumentError] = useState<ArgumentFieldError | null>(null);
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
    setArgumentError(null);
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

      <FeedbackMessages error={error} />

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
          <CardContent className="max-h-[508px] overflow-y-auto p-0">
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
                              <p className="text-xs font-medium leading-4 text-red-600">
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
