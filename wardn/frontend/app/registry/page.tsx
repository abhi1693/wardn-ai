import { AppShell } from "@/app/components/app-shell";
import type {
  MCPRegistryServerListResponse,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";

import { RegistryListClient } from "./registry-list-client";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

async function getInitialServers() {
  try {
    const response = await fetch(
      `${backendUrl}/api/v1/mcp/registry/servers?limit=50&version=latest`,
      { cache: "no-store" }
    );
    if (!response.ok) {
      return { servers: [], metadata: { count: 0, nextCursor: "" } };
    }
    return (await response.json()) as MCPRegistryServerListResponse;
  } catch {
    return { servers: [], metadata: { count: 0, nextCursor: "" } };
  }
}

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

export default async function RegistryPage() {
  const [serverList, installations] = await Promise.all([
    getInitialServers(),
    getInitialInstallations(),
  ]);

  return (
    <AppShell
      active="registry"
      eyebrow="MCP Registry"
      title="Servers"
    >
      <RegistryListClient
        initialInstallations={installations}
        initialMetadata={serverList.metadata}
        initialServers={serverList.servers}
      />
    </AppShell>
  );
}
