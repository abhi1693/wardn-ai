"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Edit2,
  KeyRound,
  Play,
  ShieldOff,
  Trash2,
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

      <section className="grid gap-3 md:grid-cols-4">
        {connectionStatuses.map((status) => {
          const Icon = status.icon;
          return (
            <div
              className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]"
              key={status.label}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">{status.label}</div>
                  <div className="mt-1 text-xs leading-4 text-muted-foreground">
                    {status.description}
                  </div>
                </div>
                <Icon className="size-4 text-muted-foreground" />
              </div>
              <div className="mt-3 text-2xl font-semibold">{statusCounts[status.label]}</div>
            </div>
          );
        })}
      </section>

      <McpTableCard>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[320px]">Connection</TableHead>
              <TableHead className="w-[220px]">Instance</TableHead>
              <TableHead className="w-[180px]">Status</TableHead>
              <TableHead className="w-[150px]">Runtime</TableHead>
              <TableHead className="w-[170px]">Version</TableHead>
              <TableHead className="w-[140px]"></TableHead>
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
                      <Link href={`${basePath}/new`}>Add connection</Link>
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              sortedInstallations.map((installation) => {
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
                        <Button
                          disabled={isMutating}
                          onClick={() => removeInstallation(installation)}
                          aria-label={`Delete ${installation.configName}`}
                          size="icon"
                          title="Delete connection"
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
      </McpTableCard>
    </div>
  );
}
