import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  Edit2,
  KeyRound,
  LockKeyhole,
  Play,
  ServerCrash,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { runtimeDisplayName, serverIconUrlFromIcons } from "@/app/mcp/mcp-list-ui";
import { DateTimeText } from "@/components/atoms/date-time-text";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
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
  annotations: Record<string, unknown>;
  description: string;
  title: string;
  toolName: string;
  toolSchemaId?: string;
};

type ConnectionInputField = {
  configured: boolean;
  description: string;
  format: string;
  name: string;
  required: boolean;
  secret: boolean;
  section: "connection" | "runtime";
};

type SafetyRisk = {
  detail: string;
  label: "High" | "Low" | "Medium";
  score: number;
  variant: "destructive" | "secondary" | "success";
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
  const availableByToolName = new Map(
    availableForConnection.map((tool) => [tool.toolName, tool])
  );

  const tools: ConnectionTool[] =
    installedTools.data?.tools.map((tool) => ({
      annotations: tool.annotations ?? {},
      description: tool.description,
      title: tool.title || tool.toolName,
      toolName: tool.toolName,
      toolSchemaId: availableByToolName.get(tool.toolName)?.toolSchemaId,
    })) ??
    availableForConnection.map((tool) => ({
      annotations: tool.annotations ?? {},
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

function runtimeFieldRows(installation: MCPServerInstallationRead): ConnectionInputField[] {
  const runtimeConfig = installation.runtimeConfig as Record<string, unknown>;
  const packageConfig = isRecord(runtimeConfig.package) ? runtimeConfig.package : {};
  const transportConfig = isRecord(runtimeConfig.transport) ? runtimeConfig.transport : {};
  const fieldGroups: Array<{
    fields: unknown;
    section: "connection" | "runtime";
  }> = [
    { fields: packageConfig.environmentVariables, section: "connection" },
    { fields: transportConfig.headers, section: "connection" },
    { fields: packageConfig.headers, section: "connection" },
    { fields: packageConfig.packageArguments, section: "runtime" },
  ];
  const rows = fieldGroups.flatMap(({ fields, section }) => {
    if (!Array.isArray(fields)) {
      return [];
    }
    return fields.filter(isRecord).map((field) => ({
      configured: field.configured === true,
      description: typeof field.description === "string" ? field.description : "",
      format: typeof field.format === "string" ? field.format : "string",
      name: String(field.name ?? ""),
      required: field.isRequired === true,
      secret: field.isSecret === true,
      section,
    }));
  });
  return rows.filter((field) => field.name);
}

function readOnlyToolCount(tools: ConnectionTool[]) {
  return tools.filter((tool) => tool.annotations.readOnlyHint === true).length;
}

function riskyToolCount(tools: ConnectionTool[]) {
  return tools.filter((tool) => tool.annotations.readOnlyHint !== true).length;
}

function destructiveToolCount(tools: ConnectionTool[]) {
  return tools.filter((tool) => tool.annotations.destructiveHint === true).length;
}

function openWorldToolCount(tools: ConnectionTool[]) {
  return tools.filter((tool) => tool.annotations.openWorldHint === true).length;
}

function toolRiskLabel(tool: ConnectionTool) {
  if (tool.annotations.destructiveHint === true) {
    return "Destructive";
  }
  if (tool.annotations.openWorldHint === true) {
    return "External";
  }
  if (tool.annotations.readOnlyHint === true) {
    return "Read-only";
  }
  return "Review";
}

function toolRiskVariant(tool: ConnectionTool) {
  if (tool.annotations.readOnlyHint === true && tool.annotations.openWorldHint !== true) {
    return "success" as const;
  }
  if (tool.annotations.destructiveHint === true) {
    return "destructive" as const;
  }
  return "secondary" as const;
}

function safetyRisk({
  fields,
  health,
  matchingPolicies,
  tools,
}: {
  fields: ConnectionInputField[];
  health: ReturnType<typeof healthSummary>;
  matchingPolicies: GuardrailPolicyRead[];
  tools: ConnectionTool[];
}): SafetyRisk {
  const missingRequired = fields.filter((field) => field.required && !field.configured).length;
  const mutatingOrUnknown = riskyToolCount(tools);
  const destructive = destructiveToolCount(tools);
  let score = 0;
  if (health.variant === "destructive") {
    score += 4;
  } else if (health.variant === "secondary" || health.variant === "outline") {
    score += 2;
  }
  score += missingRequired * 3;
  score += destructive * 3;
  score += mutatingOrUnknown > 0 ? 2 : 0;
  score += openWorldToolCount(tools) > 0 ? 1 : 0;
  if (matchingPolicies.length === 0 && tools.length > 0) {
    score += 2;
  }
  if (score >= 7) {
    return {
      detail: "Resolve required configuration and add guardrails before broad agent access.",
      label: "High",
      score,
      variant: "destructive",
    };
  }
  if (score >= 3) {
    return {
      detail: "Review guardrails and runtime health before relying on this connection.",
      label: "Medium",
      score,
      variant: "secondary",
    };
  }
  return {
    detail: "Configuration, guardrails, and runtime health show no major safety gaps.",
    label: "Low",
    score,
    variant: "success",
  };
}

function recommendedGuardrails({
  matchingPolicies,
  tools,
}: {
  matchingPolicies: GuardrailPolicyRead[];
  tools: ConnectionTool[];
}) {
  const activePolicies = matchingPolicies.filter((policy) => policy.isActive);
  const hasRequireConfirmation = activePolicies.some((policy) => policy.mode === "require_confirmation");
  const hasDeny = activePolicies.some((policy) => policy.mode === "deny");
  const riskyTools = riskyToolCount(tools);
  const destructiveTools = destructiveToolCount(tools);
  const recommendations: string[] = [];

  if (riskyTools > 0 && !hasRequireConfirmation) {
    recommendations.push("Require approval for mutating or unknown tools on this connection.");
  }
  if (destructiveTools > 0 && !hasDeny) {
    recommendations.push("Deny destructive tools unless a specific workflow needs them.");
  }
  if (openWorldToolCount(tools) > 0) {
    recommendations.push("Constrain external-network tools to trusted targets and reviewers.");
  }
  if (matchingPolicies.length === 0 && tools.length > 0) {
    recommendations.push("Generate starter guardrails so every discovered tool has an explicit rule.");
  }
  if (recommendations.length === 0) {
    recommendations.push("Existing matching guardrails cover the discovered tool set.");
  }
  return recommendations;
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
  const inputFields = runtimeFieldRows(installation);
  const requiredFields = inputFields.filter((field) => field.required);
  const requiredSecrets = requiredFields.filter((field) => field.secret);
  const missingRequiredFields = requiredFields.filter((field) => !field.configured);
  const risk = safetyRisk({ fields: inputFields, health, matchingPolicies, tools });
  const guardrailRecommendations = recommendedGuardrails({ matchingPolicies, tools });
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

      <section className="rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-sm font-semibold">Install Safety Review</div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              Configuration, validation, discovered tools, guardrails, and runtime health for this
              MCP server install.
            </p>
          </div>
          <Badge variant={risk.variant}>Risk: {risk.label}</Badge>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div className="rounded-md border border-border px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Required Inputs</div>
              <KeyRound className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-2 text-2xl font-semibold">
              {requiredFields.length - missingRequiredFields.length}/{requiredFields.length}
            </div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">
              {requiredSecrets.length} required {requiredSecrets.length === 1 ? "secret" : "secrets"}.
            </div>
          </div>

          <div className="rounded-md border border-border px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Validation Status</div>
              <ClipboardCheck className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-2">
              <Badge variant={health.variant}>{health.label}</Badge>
            </div>
            <div className="mt-2 text-xs leading-5 text-muted-foreground">
              {health.description}
            </div>
          </div>

          <div className="rounded-md border border-border px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Discovered Tools</div>
              <Wrench className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-2 text-2xl font-semibold">{tools.length}</div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">
              {readOnlyToolCount(tools)} read-only, {riskyToolCount(tools)} need review.
            </div>
          </div>

          <div className="rounded-md border border-border px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Risk Level</div>
              <ShieldAlert className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-2">
              <Badge variant={risk.variant}>{risk.label}</Badge>
            </div>
            <div className="mt-2 text-xs leading-5 text-muted-foreground">{risk.detail}</div>
          </div>

          <div className="rounded-md border border-border px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Recommended Guardrails</div>
              <ShieldCheck className="size-4 text-muted-foreground" />
            </div>
            <ul className="mt-2 space-y-1 text-xs leading-5 text-muted-foreground">
              {guardrailRecommendations.slice(0, 2).map((recommendation) => (
                <li key={recommendation}>{recommendation}</li>
              ))}
            </ul>
          </div>

          <div className="rounded-md border border-border px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Runtime Health</div>
              <ServerCrash className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-2">
              <Badge variant={health.variant}>{health.label}</Badge>
            </div>
            <div className="mt-2 text-xs leading-5 text-muted-foreground">
              {runtimeResult.data?.health?.status ||
                runtimeResult.data?.runtimeSession?.status ||
                "No active runtime session"}
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.8fr)]">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Required args and secrets
            </div>
            {inputFields.length > 0 ? (
              <div className="grid gap-2">
                {inputFields.map((field) => (
                  <div
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
                    key={`${field.section}-${field.name}`}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-semibold">{field.name}</span>
                        <Badge variant={field.section === "connection" ? "secondary" : "outline"}>
                          {field.section}
                        </Badge>
                        {field.secret ? (
                          <Badge variant="outline">
                            <LockKeyhole className="mr-1 size-3" />
                            Secret
                          </Badge>
                        ) : null}
                        {field.required ? <Badge variant="secondary">Required</Badge> : null}
                      </div>
                      {field.description ? (
                        <div className="mt-1 text-xs leading-5 text-muted-foreground">
                          {field.description}
                        </div>
                      ) : null}
                    </div>
                    <Badge
                      variant={
                        field.required && !field.configured
                          ? "destructive"
                          : field.configured
                            ? "success"
                            : "outline"
                      }
                    >
                      {field.configured ? "Configured" : field.required ? "Missing" : "Optional"}
                    </Badge>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
                This install does not declare required arguments or secrets.
              </div>
            )}
          </div>

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Guardrail recommendations
            </div>
            <div className="space-y-2">
              {guardrailRecommendations.map((recommendation) => (
                <div
                  className="rounded-md border border-border px-3 py-2 text-sm leading-6"
                  key={recommendation}
                >
                  {recommendation}
                </div>
              ))}
              <Button asChild className="mt-2" size="sm" variant="outline">
                <Link href={matchingPolicies.length > 0 ? accessHref : `${accessHref}/new`}>
                  Review guardrails
                </Link>
              </Button>
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
                  <TableHead>Risk</TableHead>
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
                        <Badge variant={toolRiskVariant(tool)}>{toolRiskLabel(tool)}</Badge>
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
                    <TableCell className="h-32 text-center" colSpan={3}>
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
            <div className="mt-1">
              <DateTimeText fallback="" value={installation.installedAt} />
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Last Updated
            </div>
            <div className="mt-1">
              <DateTimeText fallback="" value={installation.updatedAt} />
            </div>
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
