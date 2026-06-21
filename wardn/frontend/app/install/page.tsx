import { AppShell } from "@/app/components/app-shell";
import type { MCPServerInstallationListResponse } from "@/lib/api/generated/model";

import { InstalledListClient } from "./installed-list-client";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

async function getInitialInstallations() {
  try {
    const response = await fetch(`${backendUrl}/api/v1/mcp/registry/installed-servers`, {
      cache: "no-store",
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

export default async function InstallServersPage() {
  const installations = await getInitialInstallations();

  return (
    <AppShell
      active="install"
      eyebrow="MCP Runtime"
      title="Install"
    >
      <InstalledListClient initialInstallations={installations} />
    </AppShell>
  );
}
