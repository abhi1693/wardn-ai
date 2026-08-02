import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Boxes,
  Gauge,
  KeyRound,
  Network,
  ServerCog,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

import { StatusDot } from "@/components/atoms/status-dot";
import { DashboardMetricCard } from "@/components/molecules/dashboard-metric-card";
import { DashboardPanel } from "@/components/molecules/dashboard-panel";
import { HealthRow } from "@/components/molecules/health-row";
import { SignalBar } from "@/components/molecules/signal-bar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  LLMProviderCredentialRead,
  MCPCatalogSourceRead,
  OrganizationRead,
  ResourceLimitRead,
  UsageSummaryResponse,
  WorkspaceRead,
} from "@/lib/api/generated/model";

export type WorkspaceDashboardDigest = {
  activeAgentCount: number | null;
  agentCount: number | null;
  agentLoadFailed: boolean;
  attentionInstallationCount: number | null;
  enabledInstallationCount: number | null;
  installationCount: number | null;
  installationLoadFailed: boolean;
  runtimeCounts: Record<string, number> | null;
  toolCount: number | null;
  updateCount: number | null;
  workspace: WorkspaceRead;
};

type OrganizationDashboardProps = {
  catalogSources: MCPCatalogSourceRead[] | null;
  organization: OrganizationRead;
  providerCredentials: LLMProviderCredentialRead[] | null;
  resourceLimits: ResourceLimitRead[] | null;
  usage: UsageSummaryResponse | null;
  workspaceDigests: WorkspaceDashboardDigest[];
};

type NullableAggregate = {
  complete: boolean;
  value: number | null;
};

const numberFormatter = new Intl.NumberFormat("en-US");
const compactNumberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  notation: "compact",
});

function aggregateNullable(values: Array<number | null>): NullableAggregate {
  if (values.length === 0) {
    return { complete: true, value: 0 };
  }
  const knownValues = values.filter((value): value is number => value !== null);
  if (knownValues.length === 0) {
    return { complete: false, value: null };
  }
  return {
    complete: knownValues.length === values.length,
    value: knownValues.reduce((sum, value) => sum + value, 0),
  };
}

function formatCount(value: number | null | undefined) {
  return typeof value === "number" ? numberFormatter.format(value) : "n/a";
}

function formatCompactCount(value: number | null | undefined) {
  return typeof value === "number" ? compactNumberFormatter.format(value) : "n/a";
}

function formatCurrency(value: number | string | null | undefined) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 4,
    minimumFractionDigits: 2,
    style: "currency",
  }).format(Number(value || 0));
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(date);
}

function pluralize(value: number, singular: string, plural = `${singular}s`) {
  return value === 1 ? singular : plural;
}

function statusTone(status: string) {
  const normalized = status.toLowerCase();
  if (["active", "enabled", "healthy", "ok", "ready"].includes(normalized)) {
    return "success" as const;
  }
  if (["disabled", "inactive", "pending", "paused"].includes(normalized)) {
    return "warning" as const;
  }
  if (["error", "failed", "blocked"].includes(normalized)) {
    return "danger" as const;
  }
  return "neutral" as const;
}

function availabilityLabel(aggregate: NullableAggregate) {
  if (aggregate.value === null) {
    return "Unavailable";
  }
  return aggregate.complete ? "Complete" : "Partial";
}

function runtimeEntries(workspaceDigests: WorkspaceDashboardDigest[]) {
  const counts = new Map<string, number>();
  for (const digest of workspaceDigests) {
    for (const [runtime, count] of Object.entries(digest.runtimeCounts ?? {})) {
      counts.set(runtime, (counts.get(runtime) ?? 0) + count);
    }
  }
  return [...counts.entries()].sort((left, right) => right[1] - left[1]);
}

function workspaceHref(organizationId: string, workspaceId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/chat`;
}

function catalogSyncDetail(catalogSources: MCPCatalogSourceRead[] | null) {
  if (catalogSources === null) {
    return "Catalog source data unavailable";
  }
  if (catalogSources.length === 0) {
    return "No catalog sources configured";
  }
  const errored = catalogSources.filter((source) => source.lastError).length;
  const synced = catalogSources.filter((source) => source.lastSuccessAt).length;
  if (errored > 0) {
    return `${errored} ${pluralize(errored, "source")} reporting errors`;
  }
  if (synced === 0) {
    return `${catalogSources.length} ${pluralize(catalogSources.length, "source")} configured`;
  }
  return `${synced} ${pluralize(synced, "source")} synced`;
}

export function OrganizationDashboard({
  catalogSources,
  organization,
  providerCredentials,
  resourceLimits,
  usage,
  workspaceDigests,
}: OrganizationDashboardProps) {
  const workspaces = workspaceDigests.map((digest) => digest.workspace);
  const activeWorkspaces = workspaces.filter((workspace) => workspace.status === "active").length;
  const inactiveWorkspaces = Math.max(workspaces.length - activeWorkspaces, 0);
  const connectionCount = aggregateNullable(
    workspaceDigests.map((digest) => digest.installationCount)
  );
  const enabledConnections = aggregateNullable(
    workspaceDigests.map((digest) => digest.enabledInstallationCount)
  );
  const attentionConnections = aggregateNullable(
    workspaceDigests.map((digest) => digest.attentionInstallationCount)
  );
  const availableUpdates = aggregateNullable(workspaceDigests.map((digest) => digest.updateCount));
  const agents = aggregateNullable(workspaceDigests.map((digest) => digest.agentCount));
  const activeAgents = aggregateNullable(workspaceDigests.map((digest) => digest.activeAgentCount));
  const tools = aggregateNullable(workspaceDigests.map((digest) => digest.toolCount));
  const enabledCatalogSources = catalogSources?.filter((source) => source.isEnabled).length ?? null;
  const catalogErrors = catalogSources?.filter((source) => source.lastError).length ?? null;
  const activeCredentials = providerCredentials?.filter(
    (credential) => credential.isActive && credential.status === "active"
  ).length;
  const runtimeMix = runtimeEntries(workspaceDigests);
  const usageSummary = usage?.summary ?? null;
  const usageWindow = usage?.window ?? null;
  const organizationHealthy = organization.status === "active";
  const connectionHealthKnown = attentionConnections.value !== null;
  const connectionHealthy = connectionHealthKnown && attentionConnections.value === 0;
  const catalogHealthy = catalogSources !== null && (catalogErrors ?? 0) === 0;
  const providerHealthy = providerCredentials !== null && (activeCredentials ?? 0) > 0;
  const completedHealthChecks = [
    organizationHealthy,
    workspaces.length === 0 || inactiveWorkspaces === 0,
    connectionHealthy,
    catalogHealthy,
    providerHealthy,
  ].filter(Boolean).length;

  return (
    <div className="space-y-5">
      <section className="overflow-hidden rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="p-5 md:p-6">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{organization.currentUserRole}</Badge>
              <div className="inline-flex items-center gap-2 rounded-sm border border-border bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
                <StatusDot tone={statusTone(organization.status)} />
                {organization.status}
              </div>
            </div>
            <div className="mt-5 max-w-3xl">
              <h2 className="text-2xl font-semibold leading-8 text-foreground md:text-3xl md:leading-10">
                {organization.name}
              </h2>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm leading-5 text-muted-foreground">
                <span>{organization.slug}</span>
                <span>Created {formatDate(organization.createdAt)}</span>
                <span>Updated {formatDate(organization.updatedAt)}</span>
              </div>
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button asChild size="sm">
                <Link href={`/org/${encodeURIComponent(organization.id)}/workspaces`}>
                  <Boxes className="size-4" />
                  Workspaces
                </Link>
              </Button>
              <Button asChild size="sm" variant="outline">
                <Link href={`/org/${encodeURIComponent(organization.id)}/catalog`}>
                  <BookOpen className="size-4" />
                  Catalog
                </Link>
              </Button>
              <Button asChild size="sm" variant="outline">
                <Link href={`/organizations/${encodeURIComponent(organization.id)}/settings`}>
                  <ShieldCheck className="size-4" />
                  Settings
                </Link>
              </Button>
            </div>
          </div>
          <div className="border-t border-border bg-muted/30 p-5 lg:border-l lg:border-t-0">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold leading-5 text-foreground">
                  Control plane
                </div>
                <div className="text-xs leading-4 text-muted-foreground">
                  {completedHealthChecks} of 5 checks passing
                </div>
              </div>
              <Badge variant={completedHealthChecks >= 4 ? "success" : "secondary"}>
                {completedHealthChecks >= 4 ? "Stable" : "Review"}
              </Badge>
            </div>
            <div className="mt-5 space-y-4">
              <div>
                <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                  <span>Workspace status</span>
                  <span>
                    {activeWorkspaces}/{workspaces.length || 0}
                  </span>
                </div>
                <SignalBar
                  segments={[
                    { label: `${activeWorkspaces} active`, tone: "success", value: activeWorkspaces },
                    { label: `${inactiveWorkspaces} inactive`, tone: "warning", value: inactiveWorkspaces },
                  ]}
                />
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                  <span>Connection state</span>
                  <span>{availabilityLabel(connectionCount)}</span>
                </div>
                <SignalBar
                  segments={[
                    {
                      label: `${enabledConnections.value ?? 0} enabled`,
                      tone: "success",
                      value: enabledConnections.value ?? 0,
                    },
                    {
                      label: `${attentionConnections.value ?? 0} review`,
                      tone: "warning",
                      value: attentionConnections.value ?? 0,
                    },
                  ]}
                />
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-md border border-border bg-card px-2 py-3">
                  <div className="text-lg font-semibold leading-6">
                    {formatCompactCount(tools.value)}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">Tools</div>
                </div>
                <div className="rounded-md border border-border bg-card px-2 py-3">
                  <div className="text-lg font-semibold leading-6">
                    {formatCompactCount(usageSummary?.requests)}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">Requests</div>
                </div>
                <div className="rounded-md border border-border bg-card px-2 py-3">
                  <div className="text-lg font-semibold leading-6">
                    {formatCompactCount(usageSummary?.toolCalls)}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">Calls</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <DashboardMetricCard
          detail={`${activeWorkspaces} active, ${inactiveWorkspaces} inactive`}
          href={`/org/${encodeURIComponent(organization.id)}/workspaces`}
          icon={Boxes}
          label="Workspaces"
          tone="info"
          value={formatCount(workspaces.length)}
        />
        <DashboardMetricCard
          badge={availabilityLabel(connectionCount)}
          detail={
            connectionCount.value === null
              ? "Connection data unavailable"
              : `${formatCount(enabledConnections.value)} enabled, ${formatCount(
                  attentionConnections.value
                )} review`
          }
          icon={ServerCog}
          label="MCP connections"
          tone={connectionHealthy ? "success" : "warning"}
          value={formatCount(connectionCount.value)}
        />
        <DashboardMetricCard
          badge={availabilityLabel(agents)}
          detail={
            agents.value === null
              ? "Agent data unavailable"
              : `${formatCount(activeAgents.value)} active, ${formatCount(tools.value)} tools`
          }
          icon={Sparkles}
          label="Agents"
          tone={agents.value === null ? "warning" : "info"}
          value={formatCount(agents.value)}
        />
        <DashboardMetricCard
          detail={
            catalogSources === null
              ? "Catalog source data unavailable"
              : `${formatCount(enabledCatalogSources)} enabled, ${formatCount(
                  catalogErrors
                )} errors`
          }
          href={`/org/${encodeURIComponent(organization.id)}/catalog`}
          icon={BookOpen}
          label="Catalog sources"
          tone={catalogHealthy ? "success" : "warning"}
          value={formatCount(catalogSources?.length)}
        />
      </section>

      <section className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-5">
          <DashboardPanel
            action={
              <Button asChild size="sm" variant="outline">
                <Link href={`/org/${encodeURIComponent(organization.id)}/workspaces`}>
                  <Boxes className="size-4" />
                  All
                </Link>
              </Button>
            }
            description="Workspace posture, MCP connection state, agent coverage, and tool availability."
            title="Workspace fleet"
          >
            <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workspace</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Connections</TableHead>
                <TableHead>Agents</TableHead>
                <TableHead>Updates</TableHead>
                <TableHead className="w-12 text-right">Open</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workspaceDigests.length === 0 ? (
                <TableRow>
                  <TableCell className="h-28 text-center text-muted-foreground" colSpan={6}>
                    No workspaces in this organization.
                  </TableCell>
                </TableRow>
              ) : (
                workspaceDigests.map((digest) => {
                  const workspace = digest.workspace;
                  const connectionLabel =
                    digest.installationCount === null
                      ? "Unavailable"
                      : `${formatCount(digest.enabledInstallationCount)}/${formatCount(
                          digest.installationCount
                        )}`;
                  const agentLabel =
                    digest.agentCount === null
                      ? "Unavailable"
                      : `${formatCount(digest.activeAgentCount)}/${formatCount(digest.agentCount)}`;
                  const attention = digest.attentionInstallationCount ?? 0;
                  return (
                    <TableRow key={workspace.id}>
                      <TableCell>
                        <div className="min-w-48">
                          <div className="font-medium leading-5">{workspace.name}</div>
                          <div className="text-xs leading-4 text-muted-foreground">
                            {workspace.slug}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={workspace.status === "active" ? "success" : "outline"}>
                          {workspace.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <StatusDot
                            tone={
                              digest.installationLoadFailed
                                ? "warning"
                                : digest.installationCount === 0
                                  ? "neutral"
                                : attention > 0
                                  ? "danger"
                                  : "success"
                            }
                          />
                          <span className="font-mono">{connectionLabel}</span>
                        </div>
                      </TableCell>
                      <TableCell className="font-mono">{agentLabel}</TableCell>
                      <TableCell>
                        <Badge variant={(digest.updateCount ?? 0) > 0 ? "secondary" : "outline"}>
                          {digest.updateCount === null ? "n/a" : formatCount(digest.updateCount)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button aria-label={`Open ${workspace.name}`} asChild size="icon" variant="ghost">
                          <Link href={workspaceHref(organization.id, workspace.id)}>
                            <ArrowRight className="size-4" />
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
            </Table>
          </DashboardPanel>

          <DashboardPanel
            action={
              <Badge variant={availableUpdates.value ? "secondary" : "outline"}>
                {availableUpdates.value === null
                  ? "n/a"
                  : `${formatCount(availableUpdates.value)} updates`}
              </Badge>
            }
            description="Installed MCP runtime types across all loaded workspaces."
            title="Runtime mix"
          >
            {runtimeMix.length === 0 ? (
              <div className="flex min-h-28 items-center gap-3 rounded-md border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                <ServerCog className="size-4 shrink-0" />
                No runtime targets are currently loaded.
              </div>
            ) : (
              <div className="space-y-3">
                {runtimeMix.map(([runtime, count]) => (
                  <div className="space-y-2" key={runtime}>
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="font-medium text-foreground">{runtime}</span>
                      <span className="font-mono text-muted-foreground">
                        {formatCount(count)}
                      </span>
                    </div>
                    <SignalBar
                      segments={[
                        { label: `${runtime} ${count}`, tone: "info", value: count },
                        {
                          label: "Remaining",
                          tone: "neutral",
                          value: Math.max((connectionCount.value ?? count) - count, 0),
                        },
                      ]}
                    />
                  </div>
                ))}
              </div>
            )}
          </DashboardPanel>
        </div>

        <div className="min-w-0 space-y-5">
          <DashboardPanel
            description="Current readiness signals across organization-owned surfaces."
            title="Health"
          >
            <div className="-m-4">
              <HealthRow
                badge={organization.status}
                detail={organization.slug}
                icon={ShieldCheck}
                label="Organization"
                tone={statusTone(organization.status)}
              />
              <HealthRow
                badge={`${activeWorkspaces}/${workspaces.length}`}
                detail={
                  inactiveWorkspaces === 0
                    ? "All workspaces active"
                    : `${inactiveWorkspaces} workspace ${pluralize(inactiveWorkspaces, "is", "are")} inactive`
                }
                icon={Boxes}
                label="Workspace coverage"
                tone={inactiveWorkspaces === 0 ? "success" : "warning"}
              />
              <HealthRow
                badge={
                  attentionConnections.value === null
                    ? "n/a"
                    : formatCount(attentionConnections.value)
                }
                detail={
                  attentionConnections.value === null
                    ? "MCP connection checks unavailable"
                    : connectionCount.value === 0
                      ? "No MCP connections installed"
                    : connectionHealthy
                      ? "No installed servers need review"
                      : "Installed servers need review"
                }
                icon={Network}
                label="MCP health"
                tone={connectionHealthy ? "success" : "warning"}
              />
              <HealthRow
                badge={catalogSources === null ? "n/a" : formatCount(catalogErrors)}
                detail={catalogSyncDetail(catalogSources)}
                icon={BookOpen}
                label="Catalog sync"
                tone={catalogHealthy ? "success" : "warning"}
              />
              <HealthRow
                badge={
                  providerCredentials === null
                    ? "n/a"
                    : `${activeCredentials ?? 0}/${providerCredentials.length}`
                }
                detail={
                  providerCredentials === null
                    ? "Credential data unavailable"
                    : providerHealthy
                      ? "Active model provider credentials available"
                      : "No active provider credentials"
                }
                icon={KeyRound}
                label="LLM credentials"
                tone={providerHealthy ? "success" : "warning"}
              />
            </div>
          </DashboardPanel>

          <DashboardPanel
            action={
              <Button asChild size="sm" variant="outline">
                <Link href={`/org/${encodeURIComponent(organization.id)}/usage`}>
                  <Gauge className="size-4" />
                  Usage
                </Link>
              </Button>
            }
            description={
              usageWindow
                ? `${usageWindow.startDate} to ${usageWindow.endDate}`
                : "Usage summary unavailable"
            }
            title="Usage"
          >
            {usageSummary ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs text-muted-foreground">Requests</div>
                    <div className="mt-1 text-xl font-semibold leading-7">
                      {formatCount(usageSummary.requests)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Tokens</div>
                    <div className="mt-1 text-xl font-semibold leading-7">
                      {formatCompactCount(usageSummary.totalTokens)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Tool calls</div>
                    <div className="mt-1 text-xl font-semibold leading-7">
                      {formatCount(usageSummary.toolCalls)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Cost</div>
                    <div className="mt-1 text-xl font-semibold leading-7">
                      {formatCurrency(usageSummary.costUsd)}
                    </div>
                  </div>
                </div>
                <SignalBar
                  segments={[
                    {
                      label: `${usageSummary.succeeded} succeeded`,
                      tone: "success",
                      value: usageSummary.succeeded,
                    },
                    {
                      label: `${usageSummary.running} running`,
                      tone: "info",
                      value: usageSummary.running,
                    },
                    {
                      label: `${usageSummary.failed} failed`,
                      tone: "danger",
                      value: usageSummary.failed,
                    },
                  ]}
                />
              </div>
            ) : (
              <div className="flex min-h-28 items-center gap-3 rounded-md border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                <Activity className="size-4 shrink-0" />
                Usage metrics are not available for this organization.
              </div>
            )}
          </DashboardPanel>

          <DashboardPanel
            action={
              <Button asChild size="sm" variant="outline">
                <Link href={`/org/${encodeURIComponent(organization.id)}/limits`}>
                  <AlertTriangle className="size-4" />
                  Limits
                </Link>
              </Button>
            }
            description="Catalog, provider credential, and limit configuration state."
            title="Readiness"
          >
            <div className="-m-4">
              <HealthRow
                badge={catalogSources === null ? "n/a" : formatCount(catalogSources.length)}
                detail={
                  catalogSources === null
                    ? "Catalog sources unavailable"
                    : `${formatCount(enabledCatalogSources)} enabled`
                }
                label="Catalog sources"
                tone={catalogHealthy ? "success" : "warning"}
              />
              <HealthRow
                badge={
                  providerCredentials === null ? "n/a" : formatCount(providerCredentials.length)
                }
                detail={
                  providerCredentials === null
                    ? "Credentials unavailable"
                    : `${activeCredentials ?? 0} active credentials`
                }
                label="Provider credentials"
                tone={providerHealthy ? "success" : "warning"}
              />
              <HealthRow
                badge={resourceLimits === null ? "n/a" : formatCount(resourceLimits.length)}
                detail={
                  resourceLimits === null
                    ? "Limit data unavailable"
                    : `${formatCount(resourceLimits.length)} limits scoped to this organization`
                }
                label="Resource limits"
                tone={resourceLimits === null ? "warning" : "neutral"}
              />
              <HealthRow
                badge={tools.value === null ? "n/a" : formatCompactCount(tools.value)}
                detail={
                  tools.value === null
                    ? "Tool data unavailable"
                    : `${formatCount(tools.value)} assigned agent tools`
                }
                label="Agent tool surface"
                tone={tools.value === null ? "warning" : "info"}
              />
            </div>
          </DashboardPanel>
        </div>
      </section>
    </div>
  );
}
