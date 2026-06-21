"use client";

import { CheckCircle2, Edit2, Package, Play, Plus, RefreshCw, Trash2, XCircle } from "lucide-react";
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
  MCPServerInstallationToolValidationResponse,
} from "@/lib/api/generated/model";

type InstalledListClientProps = {
  initialInstallations: MCPServerInstallationRead[];
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
  if (installation.installType === "remote") {
    return "Remote endpoint";
  }
  if (installation.installType.toLowerCase() === "oci") {
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

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

export function InstalledListClient({ initialInstallations }: InstalledListClientProps) {
  const [installations, setInstallations] =
    useState<MCPServerInstallationRead[]>(initialInstallations);
  const [isLoading, setIsLoading] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [validationInstallation, setValidationInstallation] =
    useState<MCPServerInstallationRead | null>(null);
  const [validationToolName, setValidationToolName] = useState("");
  const [validationArguments, setValidationArguments] = useState("{}");
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

  function openValidation(installation: MCPServerInstallationRead) {
    setValidationInstallation(installation);
    setValidationToolName("");
    setValidationArguments("{}");
    setValidationResult(null);
    setError("");
    setNotice("");
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

    let parsedArguments: unknown;
    try {
      parsedArguments = validationArguments.trim() ? JSON.parse(validationArguments) : {};
    } catch {
      setError("Arguments must be valid JSON.");
      return;
    }
    if (!parsedArguments || Array.isArray(parsedArguments) || typeof parsedArguments !== "object") {
      setError("Arguments must be a JSON object.");
      return;
    }

    setIsValidating(true);
    setError("");
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
          arguments: parsedArguments,
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
                            onClick={() => openValidation(installation)}
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
                  setValidationResult(null);
                }}
                type="button"
                variant="outline"
              >
                Close
              </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="validation-tool-name">
                  Tool name
                </label>
                <Input
                  id="validation-tool-name"
                  onChange={(event) => setValidationToolName(event.target.value)}
                  placeholder="list_projects"
                  value={validationToolName}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="validation-arguments">
                  Arguments
                </label>
                <textarea
                  className="min-h-24 w-full rounded-md border bg-background px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  id="validation-arguments"
                  onChange={(event) => setValidationArguments(event.target.value)}
                  value={validationArguments}
                />
              </div>
            </div>

            <div className="flex justify-end">
              <Button disabled={isValidating} onClick={validateInstallation} type="button">
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
