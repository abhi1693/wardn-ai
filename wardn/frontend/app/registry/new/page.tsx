import { AppShell } from "@/app/components/app-shell";
import {
  getWorkspaceContext,
  workspaceInstallPath,
} from "@/lib/workspace-context";

import { ServerForm } from "../server-form";

export default async function NewRegistryServerPage() {
  const workspaceContext = await getWorkspaceContext();

  return (
    <AppShell
      active="registry"
      eyebrow="MCP Registry"
      title="Add server"
      workspaceContext={workspaceContext}
    >
      <ServerForm installBasePath={workspaceInstallPath(workspaceContext)} mode="create" />
    </AppShell>
  );
}
