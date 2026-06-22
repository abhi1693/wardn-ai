import { AppShell } from "@/app/components/app-shell";
import type {
  MCPRegistryServerListResponse,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";

import { InstallFormClient } from "../install-form-client";

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

async function getInitialServers() {
  try {
    const response = await fetch(
      `${backendUrl}/api/v1/mcp/registry/servers?limit=50&version=latest`,
      { cache: "no-store" }
    );
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as MCPRegistryServerListResponse;
    return data.servers;
  } catch {
    return [];
  }
}

async function getServer(serverName: string, version: string) {
  if (!serverName) {
    return null;
  }

  try {
    const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
    const response = await fetch(
      `${backendUrl}/api/v1/mcp/registry/servers/${encodedName}/versions/${encodeURIComponent(version || "latest")}`,
      { cache: "no-store" }
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as MCPRegistryServerListResponse["servers"][number];
  } catch {
    return null;
  }
}

type NewInstallPageProps = {
  searchParams: Promise<{
    serverName?: string;
    version?: string;
  }>;
};

export default async function NewInstallPage({ searchParams }: NewInstallPageProps) {
  const { serverName = "", version = "latest" } = await searchParams;
  const [installations, servers, selectedServer] = await Promise.all([
    getInitialInstallations(),
    getInitialServers(),
    getServer(serverName, version),
  ]);

  return (
    <AppShell active="install" eyebrow="MCP Runtime" title="Add MCP server">
      <InstallFormClient
        initialInstallations={installations}
        initialSelectedServer={selectedServer}
        initialServers={selectedServer ? [selectedServer, ...servers] : servers}
      />
    </AppShell>
  );
}
