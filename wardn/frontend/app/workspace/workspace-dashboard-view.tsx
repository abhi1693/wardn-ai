import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Package,
  ServerCog,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  type WorkspaceContext,
  workspaceInstallPath,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";

async function getInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  if (!path) {
    return [];
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as MCPServerInstallationListResponse;
    return data.installations;
  } catch {
    return [];
  }
}

function runtimeLabel(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === "remote") {
    return "Remote endpoint";
  }
  if (normalized === "oci") {
    return "OCI";
  }
  if (normalized === "npm") {
    return "NPM";
  }
  if (normalized === "uvx") {
    return "UVX";
  }
  return value;
}

function installationNeedsAttention(installation: MCPServerInstallationRead) {
  return installation.status !== "enabled" || Boolean(installation.installError);
}

function metricValue(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

type WorkspaceDashboardViewProps = {
  workspaceContext: WorkspaceContext;
};

export async function WorkspaceDashboardView({ workspaceContext }: WorkspaceDashboardViewProps) {
  const workspace = workspaceContext.selectedWorkspace;
  if (!workspace) {
    redirect("/");
  }

  const installations = await getInstallations(workspaceContext);
  const installPath = workspaceInstallPath(workspaceContext);
  const uniqueServerCount = new Set(installations.map((installation) => installation.serverName))
    .size;
  const enabledCount = installations.filter((installation) => installation.status === "enabled").length;
  const updateCount = installations.filter((installation) => installation.updateAvailable).length;
  const attentionCount = installations.filter(installationNeedsAttention).length;
  const runtimeCounts = installations.reduce<Record<string, number>>((result, installation) => {
    const label = runtimeLabel(installation.installType);
    result[label] = (result[label] ?? 0) + 1;
    return result;
  }, {});

  return (
    <AppShell
      active="workspace-dashboard"
      eyebrow="Workspace"
      title={workspace.name}
      workspaceContext={workspaceContext}
    >
      <section className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Server instances</div>
                <div className="mt-2 text-2xl font-semibold">
                  {metricValue(installations.length)}
                </div>
              </div>
              <ServerCog className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Supported servers used</div>
                <div className="mt-2 text-2xl font-semibold">{metricValue(uniqueServerCount)}</div>
              </div>
              <Boxes className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Enabled</div>
                <div className="mt-2 text-2xl font-semibold">{metricValue(enabledCount)}</div>
              </div>
              <CheckCircle2 className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Needs attention</div>
                <div className="mt-2 text-2xl font-semibold">{metricValue(attentionCount)}</div>
              </div>
              <AlertTriangle className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <CardHeader>
            <CardTitle>Workspace health</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between rounded-md border px-3 py-3">
              <div>
                <div className="text-sm font-medium">Runtime status</div>
                <div className="text-sm text-muted-foreground">
                  {attentionCount === 0
                    ? "No installation errors are currently reported."
                    : "One or more server instances need review."}
                </div>
              </div>
              <Badge variant={attentionCount === 0 ? "success" : "secondary"}>
                {attentionCount === 0 ? "Healthy" : "Review"}
              </Badge>
            </div>
            <div className="flex items-center justify-between rounded-md border px-3 py-3">
              <div>
                <div className="text-sm font-medium">Available updates</div>
                <div className="text-sm text-muted-foreground">
                  {updateCount === 0
                    ? "Installed versions match the supported catalog."
                    : "Updates are available for configured server instances."}
                </div>
              </div>
              <Badge variant={updateCount === 0 ? "outline" : "secondary"}>
                {metricValue(updateCount)}
              </Badge>
            </div>
            {installations.length === 0 ? (
              <div className="rounded-md border border-dashed px-3 py-8 text-center">
                <Package className="mx-auto mb-2 size-5 text-muted-foreground" />
                <div className="text-sm font-medium">No MCP servers installed</div>
                <div className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                  Add a server instance to make tools available from this workspace.
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Runtime mix</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {Object.entries(runtimeCounts).length === 0 ? (
                <div className="text-sm text-muted-foreground">No runtime targets configured.</div>
              ) : (
                Object.entries(runtimeCounts).map(([runtime, count]) => (
                  <div className="flex items-center justify-between rounded-md border px-3 py-2" key={runtime}>
                    <span className="text-sm">{runtime}</span>
                    <span className="text-sm font-medium">{metricValue(count)}</span>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Workspace</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Slug</span>
                <span className="font-mono">{workspace.slug}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Status</span>
                <Badge variant="outline">{workspace.status}</Badge>
              </div>
              <div className="grid gap-2 pt-2">
                <Button asChild variant="outline">
                  <Link href={installPath}>
                    <ServerCog className="size-4" />
                    Manage installations
                  </Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>
    </AppShell>
  );
}
