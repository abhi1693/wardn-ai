import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Edit2,
  Play,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { runtimeDisplayName, serverIconUrlFromIcons } from "@/app/mcp/mcp-list-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage, readApiResponseBody } from "@/lib/api/errors";
import { backendCookieHeader, backendJson, backendPath } from "@/lib/api/server";
import {
  type WorkspaceContext,
  workspaceInstallPath,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";
import type {
  AgentAvailableToolListResponse,
  GuardrailPolicyListResponse,
  GuardrailPolicyRead,
  MCPGatewayToolApprovalListResponse,
  MCPRuntimeInstallationControlResponse,
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
  MCPServerInstallationToolsResponse,
} from "@/lib/api/generated/model";
import { ConnectionApprovalsClient } from "./connection-approvals-client";

type ConnectionTool = {
  description: string;
  title: string;
  toolName: string;
  toolSchemaId?: string;
};

type OptionalResult<T> = {
  data: T | null;
  error: string;
};

async function optionalBackendJson<T>(path: string, fallback: string): Promise<OptionalResult<T>> {
  try {
    const cookieHeader = await backendCookieHeader();
    const headers = new Headers();
    if (cookieHeader) {
      headers.set("cookie", cookieHeader);
    }
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(15_000),
    });
    const body = await readApiResponseBody(response);
    if (!response.ok) {
      return { data: null, error: apiErrorMessage(body, fallback) };
    }
    return { data: body as T, error: "" };
  } catch (caught) {
    return {
      data: null,
      error: caught instanceof Error ? caught.message : fallback,
    };
  }
}

async function getInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  if (!path) {
    return [];
  }
  const data = await backendJson<MCPServerInstallationListResponse>(path);
  return data.installations;
}

async function getAvailableTools(organizationId: string, workspaceId: string) {
  const payload = await backendJson<AgentAvailableToolListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/available-tools`
  );
  return payload.tools;
}

async function getAccessRules(organizationId: string, workspaceId: string) {
  const payload = await backendJson<GuardrailPolicyListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/guardrails/policies`
  );
  return payload.policies;
}

async function getConnectionTools(
  organizationId: string,
  workspaceId: string,
  installationId: string,
  availableTools: Awaited<ReturnType<typeof getAvailableTools>>,
) {
  const installedTools = await optionalBackendJson<MCPServerInstallationToolsResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(
      workspaceId
    )}/mcp/registry/installed-server-configs/${encodeURIComponent(installationId)}/tools`,
    "Connection tools could not be loaded."
  );
  const availableForConnection = availableTools.filter(
    (tool) => tool.installationId === installationId
  );
  const schemaIdsByToolName = new Map(
    availableForConnection.map((tool) => [tool.toolName, tool.toolSchemaId])
  );

  const tools: ConnectionTool[] =
    installedTools.data?.tools.map((tool) => ({
      description: tool.description,
      title: tool.title || tool.toolName,
      toolName: tool.toolName,
      toolSchemaId: schemaIdsByToolName.get(tool.toolName),
    })) ??
    availableForConnection.map((tool) => ({
      description: tool.description,
      title: tool.title || tool.toolName,
      toolName: tool.toolName,
      toolSchemaId: tool.toolSchemaId,
    }));

  return {
    error: installedTools.error,
    tools: tools.sort((left, right) => left.toolName.localeCompare(right.toolName)),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValues(value: unknown) {
  if (typeof value === "string") {
    return [value];
  }
  if (Array.isArray(value)) {
    return value.filter((entry): entry is string => typeof entry === "string");
  }
  return [];
}

function policyTouchesConnection(
  policy: GuardrailPolicyRead,
  toolSchemaIds: Set<string>,
  toolNames: Set<string>,
) {
  const conditions = policy.conditions;
  if (!isRecord(conditions) || !Array.isArray(conditions.rules)) {
    return true;
  }
  const rules = conditions.rules.filter(isRecord);
  if (rules.length === 0) {
    return true;
  }

  return rules.some((rule) => {
    const field = typeof rule.field === "string" ? rule.field : "";
    const values = stringValues(rule.value);
    if (field === "tool_schema_id") {
      return values.some((value) => toolSchemaIds.has(value));
    }
    if (field === "tool_name") {
      return values.some((value) => toolNames.has(value));
    }
    return false;
  });
}

function targetLabel(policy: GuardrailPolicyRead, toolsBySchemaId: Map<string, ConnectionTool>) {
  const conditions = policy.conditions;
  if (!isRecord(conditions) || !Array.isArray(conditions.rules) || conditions.rules.length === 0) {
    return "All tools in this workspace";
  }
  const labels = conditions.rules.filter(isRecord).flatMap((rule) => {
    const field = typeof rule.field === "string" ? rule.field : "";
    const values = stringValues(rule.value);
    if (field === "tool_schema_id" && values.length > 0) {
      return values.map((value) => toolsBySchemaId.get(value)?.toolName ?? "Selected tool");
    }
    if (field === "tool_name" && values.length > 0) {
      return values;
    }
    return [];
  });
  return labels.length > 0 ? labels.join(", ") : "Custom condition";
}

function modeLabel(mode: string) {
  if (mode === "require_confirmation") {
    return "Needs approval";
  }
  if (mode === "allow") {
    return "Allowed";
  }
  if (mode === "deny") {
    return "Blocked";
  }
  return mode;
}

function modeVariant(mode: string) {
  if (mode === "allow") {
    return "success" as const;
  }
  if (mode === "deny") {
    return "destructive" as const;
  }
  return "secondary" as const;
}

function healthSummary(
  installation: MCPServerInstallationRead,
  runtimeState: MCPRuntimeInstallationControlResponse | null,
  runtimeError: string,
) {
  const detail = [installation.status, installation.installError ?? ""].join(" ").toLowerCase();
  if (
    detail.includes("credential") ||
    detail.includes("secret") ||
    detail.includes("token") ||
    detail.includes("unauthorized") ||
    detail.includes("authentication") ||
    detail.includes("401")
  ) {
    return {
      description: installation.installError || "Credentials are missing or rejected.",
      label: "Needs credential",
      variant: "secondary" as const,
    };
  }
  if (
    detail.includes("policy") ||
    detail.includes("guardrail") ||
    detail.includes("forbidden") ||
    detail.includes("403")
  ) {
    return {
      description: installation.installError || "A policy is blocking this connection.",
      label: "Blocked by policy",
      variant: "destructive" as const,
    };
  }
  if (installation.installError || installation.status !== "enabled") {
    return {
      description: installation.installError || `Connection status is ${installation.status}.`,
      label: "Unhealthy",
      variant: "destructive" as const,
    };
  }
  if (runtimeState?.health) {
    return {
      description: runtimeState.health.message || runtimeState.health.status,
      label: runtimeState.health.ready && runtimeState.health.healthy ? "Healthy" : "Unhealthy",
      variant: runtimeState.health.ready && runtimeState.health.healthy ? "success" as const : "destructive" as const,
    };
  }
  if (runtimeError) {
    return {
      description: runtimeError,
      label: "Health unavailable",
      variant: "outline" as const,
    };
  }
  return {
    description: "Ready to start when workspace chat uses this connection.",
    label: "Healthy",
    variant: "success" as const,
  };
}

function formatDate(value?: string | null) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

type ConnectionDetailViewProps = {
  installationId: string;
  workspaceContext: WorkspaceContext;
};

export async function ConnectionDetailView({
  installationId,
  workspaceContext,
}: ConnectionDetailViewProps) {
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  const basePath = workspaceInstallPath(workspaceContext);
  const installations = await getInstallations(workspaceContext);
  const installation = installations.find((item) => item.id === installationId);

  if (!installation) {
    notFound();
  }

  const [availableTools, policies, runtimeResult, approvalsResult] = await Promise.all([
    getAvailableTools(organization.id, workspace.id),
    getAccessRules(organization.id, workspace.id),
    optionalBackendJson<MCPRuntimeInstallationControlResponse>(
      `/api/v1/organizations/${encodeURIComponent(
        organization.id
      )}/workspaces/${encodeURIComponent(workspace.id)}/mcp/runtime/installations/${encodeURIComponent(
        installation.id
      )}`,
      "Runtime health could not be loaded."
    ),
    optionalBackendJson<MCPGatewayToolApprovalListResponse>(
      `/api/v1/organizations/${encodeURIComponent(
        organization.id
      )}/workspaces/${encodeURIComponent(
        workspace.id
      )}/mcp/gateway/tool-approvals?installationId=${encodeURIComponent(
        installation.id
      )}&status=pending&limit=25`,
      "Gateway approvals could not be loaded."
    ),
  ]);
  const { tools, error: toolsError } = await getConnectionTools(
    organization.id,
    workspace.id,
    installation.id,
    availableTools
  );
  const toolSchemaIds = new Set(
    tools.flatMap((tool) => (tool.toolSchemaId ? [tool.toolSchemaId] : []))
  );
  const toolNames = new Set(tools.map((tool) => tool.toolName));
  const toolsBySchemaId = new Map(
    tools.flatMap((tool) => (tool.toolSchemaId ? [[tool.toolSchemaId, tool] as const] : []))
  );
  const matchingPolicies = policies
    .filter((policy) => policyTouchesConnection(policy, toolSchemaIds, toolNames))
    .sort((left, right) => {
      const priorityCompare = left.priority - right.priority;
      return priorityCompare !== 0 ? priorityCompare : left.name.localeCompare(right.name);
    });
  const health = healthSummary(installation, runtimeResult.data, runtimeResult.error);
  const iconUrl = serverIconUrlFromIcons(installation.server.icons);
  const displayName = installation.server.title || installation.serverName;
  const accessHref = `/org/${encodeURIComponent(
    organization.id
  )}/workspace/${encodeURIComponent(workspace.id)}/guardrails`;

  return (
    <AppShell
      active="install"
      actions={
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link href={basePath}>
              <ArrowLeft className="size-4" />
              Connections
            </Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={`${basePath}/${encodeURIComponent(installation.id)}/validate`}>
              <Play className="size-4" />
              Check
            </Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={`${basePath}/${encodeURIComponent(installation.id)}/edit`}>
              <Edit2 className="size-4" />
              Edit
            </Link>
          </Button>
        </div>
      }
      eyebrow="Connection"
      title={installation.configName}
      workspaceContext={workspaceContext}
    >
      <section className="rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-muted-foreground">
              {iconUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  alt=""
                  className="size-full object-contain"
                  loading="lazy"
                  referrerPolicy="no-referrer"
                  src={iconUrl}
                />
              ) : (
                <Wrench className="size-5" />
              )}
            </div>
            <div className="min-w-0">
              <h2 className="text-xl font-semibold">{displayName}</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                {installation.server.description ||
                  "This connection exposes tools that workspace chat can use through Wardn."}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant={health.variant}>{health.label}</Badge>
                <Badge variant="outline">{runtimeDisplayName(installation.installType)}</Badge>
                <Badge variant={installation.updateAvailable ? "secondary" : "outline"}>
                  {installation.updateAvailable ? "Update available" : `Version ${installation.installedVersion}`}
                </Badge>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Health</div>
                <div className="mt-1 text-xs leading-4 text-muted-foreground">
                  {health.description}
                </div>
              </div>
              {health.variant === "success" ? (
                <CheckCircle2 className="size-4 text-emerald-700" />
              ) : (
                <AlertTriangle className="size-4 text-muted-foreground" />
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Capabilities</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Tools this connection exposes.
                </div>
              </div>
              <Wrench className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{tools.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Assistant</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Workspace chat availability.
                </div>
              </div>
              <Bot className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">
              {installation.status === "enabled" ? "Ready" : "Off"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Access Rules</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Matching workspace rules.
                </div>
              </div>
              <ShieldCheck className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{matchingPolicies.length}</div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
        <Card>
          <CardHeader>
            <CardTitle>What Can This Connection Do?</CardTitle>
          </CardHeader>
          <CardContent>
            {toolsError && tools.length === 0 ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                {toolsError}
              </div>
            ) : null}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tool</TableHead>
                  <TableHead>Description</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tools.length > 0 ? (
                  tools.map((tool) => (
                    <TableRow key={tool.toolName}>
                      <TableCell>
                        <div className="min-w-48">
                          <div className="font-medium">{tool.title || tool.toolName}</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {tool.toolName}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="text-sm leading-6">
                          {tool.description || "No description provided."}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell className="h-32 text-center" colSpan={2}>
                      <div className="mx-auto max-w-md">
                        <div className="font-medium text-foreground">No tools discovered</div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          Check the connection to refresh its capabilities.
                        </div>
                        <Button asChild className="mt-4" size="sm">
                          <Link href={`${basePath}/${encodeURIComponent(installation.id)}/validate`}>
                            Check connection
                          </Link>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <div className="space-y-5">
          <ConnectionApprovalsClient
            initialApprovals={approvalsResult.data?.approvals ?? []}
            loadError={approvalsResult.error}
            organizationId={organization.id}
            workspaceId={workspace.id}
          />

          <Card>
            <CardHeader>
              <CardTitle>Workspace Assistant Access</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-md border border-border px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium">Workspace Assistant</div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      Enabled workspace connections are available in chat automatically.
                    </div>
                  </div>
                  <Badge variant={installation.status === "enabled" ? "success" : "secondary"}>
                    {installation.status === "enabled" ? "Available" : "Unavailable"}
                  </Badge>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>What Rules Apply?</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {matchingPolicies.length > 0 ? (
                matchingPolicies.map((policy) => (
                  <div className="rounded-md border border-border px-3 py-3" key={policy.id}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-medium">{policy.name}</div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {targetLabel(policy, toolsBySchemaId)}
                        </div>
                      </div>
                      <Badge variant={policy.isActive ? modeVariant(policy.mode) : "outline"}>
                        {policy.isActive ? modeLabel(policy.mode) : "Inactive"}
                      </Badge>
                    </div>
                    {policy.description ? (
                      <div className="mt-2 text-sm leading-6 text-muted-foreground">
                        {policy.description}
                      </div>
                    ) : null}
                  </div>
                ))
              ) : (
                <div className="rounded-md border border-dashed border-border px-3 py-6 text-center">
                  <div className="font-medium">No matching access rules</div>
                  <div className="mx-auto mt-1 max-w-sm text-sm leading-6 text-muted-foreground">
                    Tool calls are not constrained by a rule that targets this connection.
                  </div>
                  <Button asChild className="mt-4" size="sm" variant="outline">
                    <Link href={`${accessHref}/new`}>New rule</Link>
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      <details className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <summary className="cursor-pointer text-sm font-semibold">
          Advanced runtime details
        </summary>
        <div className="mt-4 grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Runtime
            </div>
            <div className="mt-1">{runtimeDisplayName(installation.installType)}</div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Runtime Provider
            </div>
            <div className="mt-1">{installation.runtimeProvider}</div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Installed Version
            </div>
            <div className="mt-1">{installation.installedVersion}</div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Installed
            </div>
            <div className="mt-1">{formatDate(installation.installedAt)}</div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Last Updated
            </div>
            <div className="mt-1">{formatDate(installation.updatedAt)}</div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Runtime State
            </div>
            <div className="mt-1">
              {runtimeResult.data?.health?.status ||
                runtimeResult.data?.runtimeSession?.status ||
                "No active session"}
            </div>
          </div>
          <div className="md:col-span-2 xl:col-span-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Install Path
            </div>
            <div className="mt-1 break-all font-mono text-xs">{installation.installPath}</div>
          </div>
        </div>
      </details>
    </AppShell>
  );
}
