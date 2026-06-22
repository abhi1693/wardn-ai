"use client";

import { Edit2, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  FeedbackMessages,
  McpTableCard,
  RuntimeBadge,
  ServerIdentityCell,
  mcpServerDetailUrl,
  responseErrorMessage,
  runtimeDisplayName,
  serverIconUrlFromIcons,
} from "@/app/mcp/mcp-list-ui";
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

type InstalledListClientProps = {
  basePath: string;
  initialInstallations: MCPServerInstallationRead[];
  organizationId: string;
};

function editInstallUrl(basePath: string, installationId: string) {
  return `${basePath}/${encodeURIComponent(installationId)}/edit`;
}

export function InstalledListClient({
  basePath,
  initialInstallations,
  organizationId,
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

  return (
    <div className="space-y-4">
      <FeedbackMessages error={error} notice={notice} />

      <McpTableCard>
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
                const iconUrl = serverIconUrlFromIcons(installation.server.icons);

                return (
                  <TableRow key={installation.id}>
                    <TableCell>
                      <ServerIdentityCell
                        href={mcpServerDetailUrl(
                          organizationId,
                          installation.serverName,
                          installation.installedVersion
                        )}
                        iconUrl={iconUrl}
                        name={installation.serverName}
                        title={installation.server.title || installation.serverName}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="font-medium">{installation.configName}</div>
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
                        <Button asChild disabled={isMutating} size="icon" type="button" variant="outline">
                          <Link
                            aria-label={`Edit ${installation.configName}`}
                            href={editInstallUrl(basePath, installation.id)}
                            title="Edit installation"
                          >
                            <Edit2 className="size-4" />
                          </Link>
                        </Button>
                        <Button asChild disabled={isMutating} size="icon" type="button" variant="outline">
                          <Link
                            aria-label={`Validate ${installation.configName}`}
                            href={`${basePath}/${encodeURIComponent(installation.id)}/validate`}
                            title="Validate tools"
                          >
                            <Play className="size-4" />
                          </Link>
                        </Button>
                        <Button
                          disabled={isMutating}
                          onClick={() => removeInstallation(installation)}
                          aria-label={`Delete ${installation.configName}`}
                          size="icon"
                          title="Delete installation"
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
