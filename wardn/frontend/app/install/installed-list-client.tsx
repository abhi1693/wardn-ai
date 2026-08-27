"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Edit2,
  KeyRound,
  Play,
  ShieldOff,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";

import {
  FeedbackMessages,
  McpTableCard,
  RuntimeBadge,
  ServerIdentityCell,
  runtimeDisplayName,
  serverIconUrlFromIcons,
} from "@/app/mcp/mcp-list-ui";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { SearchField } from "@/components/molecules/search-field";
import { MetricStrip } from "@/components/organisms/metric-strip";
import { useUrlState } from "@/hooks/use-url-state";
import type { MCPServerInstallationRead } from "@/lib/api/generated/model";
import { workspaceMcpRegistryUninstallServerConfig } from "@/lib/api/generated/workspace-mcp-registry/workspace-mcp-registry";

type InstalledListClientProps = {
  basePath: string;
  initialInstallations: MCPServerInstallationRead[];
  organizationId: string;
  workspaceId: string;
};

function editInstallUrl(basePath: string, installationId: string) {
  return `${basePath}/${encodeURIComponent(installationId)}/edit`;
}

function connectionDetailUrl(basePath: string, installationId: string) {
  return `${basePath}/${encodeURIComponent(installationId)}`;
}

type ConnectionStatusLabel =
  | "Needs credential"
  | "Connected"
  | "Blocked by policy"
  | "Unhealthy";

const ALL_FILTER_VALUE = "__all__";

type ConnectionStatus = {
  detail: string;
  icon: typeof CheckCircle2;
  label: ConnectionStatusLabel;
  variant: "success" | "secondary" | "destructive" | "outline";
};

const connectionStatuses: Array<{
  description: string;
  icon: typeof CheckCircle2;
  label: ConnectionStatusLabel;
}> = [
  {
    description: "Missing or rejected credentials.",
    icon: KeyRound,
    label: "Needs credential",
  },
  {
    description: "Ready for agent tool use.",
    icon: CheckCircle2,
    label: "Connected",
  },
  {
    description: "A policy is preventing use.",
    icon: ShieldOff,
    label: "Blocked by policy",
  },
  {
    description: "Runtime or upstream health needs attention.",
    icon: AlertTriangle,
    label: "Unhealthy",
  },
];

function connectionStatus(installation: MCPServerInstallationRead): ConnectionStatus {
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
      detail: installation.installError || "Credentials are missing or rejected.",
      icon: KeyRound,
      label: "Needs credential",
      variant: "secondary",
    };
  }
  if (
    detail.includes("policy") ||
    detail.includes("guardrail") ||
    detail.includes("forbidden") ||
    detail.includes("403")
  ) {
    return {
      detail: installation.installError || "A policy is blocking this connection.",
      icon: ShieldOff,
      label: "Blocked by policy",
      variant: "destructive",
    };
  }
  if (installation.status === "enabled" && !installation.installError) {
    return {
      detail: "Ready for agent tool use.",
      icon: CheckCircle2,
      label: "Connected",
      variant: "success",
    };
  }
  return {
    detail: installation.installError || `Connection status is ${installation.status}.`,
    icon: AlertTriangle,
    label: "Unhealthy",
    variant: "destructive",
  };
}

type FilterOption = {
  label: string;
  value: string;
};

function connectionTypeLabel(installation: MCPServerInstallationRead) {
  return installation.server.title || installation.serverName;
}

function normalizedSearchText(value: string | null | undefined) {
  return (value || "").trim().toLowerCase();
}

function formatResultCount(count: number, total: number) {
  const noun = total === 1 ? "connection" : "connections";
  return `${count} of ${total} ${noun}`;
}

function sortedFilterOptions(options: Map<string, string>): FilterOption[] {
  return Array.from(options.entries())
    .map(([value, label]) => ({ label, value }))
    .sort((left, right) => left.label.localeCompare(right.label));
}

type InstallationActionLinkProps = {
  children: ReactNode;
  disabled: boolean;
  href: string;
  label: string;
  title: string;
};

function InstallationActionLink({
  children,
  disabled,
  href,
  label,
  title,
}: InstallationActionLinkProps) {
  if (disabled) {
    return (
      <Button
        aria-label={label}
        disabled
        size="icon"
        title={title}
        type="button"
        variant="outline"
      >
        {children}
      </Button>
    );
  }

  return (
    <Button asChild size="icon" variant="outline">
      <Link aria-label={label} href={href} title={title}>
        {children}
      </Link>
    </Button>
  );
}

export function InstalledListClient({
  basePath,
  initialInstallations,
  organizationId,
  workspaceId,
}: InstalledListClientProps) {
  const [installations, setInstallations] =
    useState<MCPServerInstallationRead[]>(initialInstallations);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [searchQuery, setSearchQuery] = useUrlState("connections-query");
  const [statusFilter, setStatusFilter] = useUrlState(
    "connections-status",
    ALL_FILTER_VALUE
  );
  const [runtimeFilter, setRuntimeFilter] = useUrlState(
    "connections-runtime",
    ALL_FILTER_VALUE
  );
  const [connectionTypeFilter, setConnectionTypeFilter] = useUrlState(
    "connections-type",
    ALL_FILTER_VALUE
  );

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

  const statusCounts = useMemo(() => {
    const counts: Record<ConnectionStatusLabel, number> = {
      "Needs credential": 0,
      Connected: 0,
      "Blocked by policy": 0,
      Unhealthy: 0,
    };
    installations.forEach((installation) => {
      counts[connectionStatus(installation).label] += 1;
    });
    return counts;
  }, [installations]);

  const statusFilterOptions = useMemo(
    () =>
      connectionStatuses
        .filter((status) => statusCounts[status.label] > 0)
        .map((status) => ({ label: status.label, value: status.label })),
    [statusCounts]
  );

  const runtimeFilterOptions = useMemo(() => {
    const options = new Map<string, string>();
    installations.forEach((installation) => {
      const label = runtimeDisplayName(installation.installType);
      options.set(label, label);
    });
    return sortedFilterOptions(options);
  }, [installations]);

  const connectionTypeFilterOptions = useMemo(() => {
    const options = new Map<string, string>();
    installations.forEach((installation) => {
      options.set(installation.serverName, connectionTypeLabel(installation));
    });
    return sortedFilterOptions(options);
  }, [installations]);

  const filteredInstallations = useMemo(() => {
    const query = normalizedSearchText(searchQuery);

    return sortedInstallations.filter((installation) => {
      const status = connectionStatus(installation);
      const runtimeLabel = runtimeDisplayName(installation.installType);

      if (statusFilter !== ALL_FILTER_VALUE && status.label !== statusFilter) {
        return false;
      }
      if (runtimeFilter !== ALL_FILTER_VALUE && runtimeLabel !== runtimeFilter) {
        return false;
      }
      if (
        connectionTypeFilter !== ALL_FILTER_VALUE &&
        installation.serverName !== connectionTypeFilter
      ) {
        return false;
      }
      if (!query) {
        return true;
      }

      const searchableText = [
        connectionTypeLabel(installation),
        installation.serverName,
        installation.configName,
        runtimeLabel,
        installation.installType,
        installation.runtimeProvider,
      ]
        .map(normalizedSearchText)
        .join(" ");

      return searchableText.includes(query);
    });
  }, [
    connectionTypeFilter,
    runtimeFilter,
    searchQuery,
    sortedInstallations,
    statusFilter,
  ]);

  const hasActiveFilters =
    normalizedSearchText(searchQuery).length > 0 ||
    statusFilter !== ALL_FILTER_VALUE ||
    runtimeFilter !== ALL_FILTER_VALUE ||
    connectionTypeFilter !== ALL_FILTER_VALUE;

  function clearFilters() {
    setSearchQuery("");
    setStatusFilter(ALL_FILTER_VALUE);
    setRuntimeFilter(ALL_FILTER_VALUE);
    setConnectionTypeFilter(ALL_FILTER_VALUE);
  }

  async function removeInstallation(installation: MCPServerInstallationRead) {
    setIsMutating(true);
    setError("");
    setNotice("");
    try {
      await workspaceMcpRegistryUninstallServerConfig(
        organizationId,
        workspaceId,
        installation.id
      );
      setInstallations((current) => current.filter((item) => item.id !== installation.id));
      setNotice("Connection removed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Connection could not be removed.");
    } finally {
      setIsMutating(false);
    }
  }

  return (
    <div className="space-y-4">
      <FeedbackMessages error={error} notice={notice} />

      <MetricStrip
        className="md:grid-cols-4"
        items={connectionStatuses.map((status) => ({
          detail: status.description,
          icon: status.icon,
          label: status.label,
          value: statusCounts[status.label],
        }))}
      />

      <McpTableCard>
        {sortedInstallations.length > 0 ? (
          <div className="border-b border-border bg-card px-4 py-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
              <div className="grid flex-1 gap-3 md:grid-cols-2 xl:grid-cols-[minmax(260px,1.35fr)_minmax(160px,0.75fr)_minmax(160px,0.75fr)_minmax(190px,0.85fr)]">
                <SearchField
                  aria-label="Search connections"
                  id="connection-search"
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Connection, instance, or type"
                  value={searchQuery}
                />

                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">Runtime</span>
                  <Select onValueChange={setRuntimeFilter} value={runtimeFilter}>
                    <SelectTrigger aria-label="Filter by runtime">
                      <SelectValue placeholder="All runtimes" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_FILTER_VALUE}>All runtimes</SelectItem>
                      {runtimeFilterOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>

                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">Status</span>
                  <Select onValueChange={setStatusFilter} value={statusFilter}>
                    <SelectTrigger aria-label="Filter by status">
                      <SelectValue placeholder="All statuses" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_FILTER_VALUE}>All statuses</SelectItem>
                      {statusFilterOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>

                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">
                    Connection type
                  </span>
                  <Select onValueChange={setConnectionTypeFilter} value={connectionTypeFilter}>
                    <SelectTrigger aria-label="Filter by connection type">
                      <SelectValue placeholder="All connection types" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_FILTER_VALUE}>All connection types</SelectItem>
                      {connectionTypeFilterOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
              </div>

              <div className="flex items-center justify-between gap-3 xl:justify-end">
                <div className="text-sm text-muted-foreground">
                  {formatResultCount(filteredInstallations.length, sortedInstallations.length)}
                </div>
                {hasActiveFilters ? (
                  <Button onClick={clearFilters} size="sm" type="button" variant="ghost">
                    <X className="size-4" />
                    Clear
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[320px]">Connection</TableHead>
              <TableHead className="w-[220px]">Instance</TableHead>
              <TableHead className="w-[180px]">Status</TableHead>
              <TableHead className="w-[150px]">Runtime</TableHead>
              <TableHead className="w-[170px]">Version</TableHead>
              <TableHead className="w-[140px] text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedInstallations.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-44 text-center">
                  <div className="mx-auto max-w-md">
                    <div className="text-base font-semibold text-foreground">
                      No connections yet
                    </div>
                    <div className="mt-1 text-sm leading-6 text-muted-foreground">
                      Add a connection to give the workspace agent useful tools. Wardn will keep
                      credentials, runtime state, and access decisions visible here.
                    </div>
                    <Button asChild className="mt-4" size="sm">
                      <Link href={`${basePath}/new`}>New connection</Link>
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ) : filteredInstallations.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-44 text-center">
                  <div className="mx-auto max-w-md">
                    <div className="text-base font-semibold text-foreground">
                      No connections match these filters
                    </div>
                    <div className="mt-1 text-sm leading-6 text-muted-foreground">
                      Adjust the search text or clear filters to see the installed connections.
                    </div>
                    <Button
                      className="mt-4"
                      onClick={clearFilters}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      Clear filters
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              filteredInstallations.map((installation) => {
                const iconUrl = serverIconUrlFromIcons(installation.server.icons);
                const status = connectionStatus(installation);

                return (
                  <TableRow key={installation.id}>
                    <TableCell>
                      <ServerIdentityCell
                        href={connectionDetailUrl(basePath, installation.id)}
                        iconUrl={iconUrl}
                        name={installation.serverName}
                        title={installation.server.title || installation.serverName}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="font-medium">{installation.configName}</div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <Badge variant={status.variant}>{status.label}</Badge>
                        {status.label !== "Connected" ? (
                          <div className="max-w-72 truncate text-xs text-muted-foreground">
                            {status.detail}
                          </div>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <RuntimeBadge label={runtimeDisplayName(installation.installType)} />
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
                        <InstallationActionLink
                          disabled={isMutating}
                          href={editInstallUrl(basePath, installation.id)}
                          label={`Edit ${installation.configName}`}
                          title="Edit connection"
                        >
                          <Edit2 className="size-4" />
                        </InstallationActionLink>
                        <InstallationActionLink
                          disabled={isMutating}
                          href={`${basePath}/${encodeURIComponent(installation.id)}/validate`}
                          label={`Validate ${installation.configName}`}
                          title="Check connection"
                        >
                          <Play className="size-4" />
                        </InstallationActionLink>
                        <ConfirmActionDialog
                          actionLabel="Remove connection"
                          description="Agents will immediately lose access to its tools and runtime configuration."
                          onConfirm={() => removeInstallation(installation)}
                          title={`Remove ${installation.configName}?`}
                          variant="destructive"
                        >
                          <Button
                            aria-label={`Delete ${installation.configName}`}
                            disabled={isMutating}
                            size="icon"
                            title="Delete connection"
                            type="button"
                            variant="outline"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </ConfirmActionDialog>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </McpTableCard>
    </div>
  );
}
