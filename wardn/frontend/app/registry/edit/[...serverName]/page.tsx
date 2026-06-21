import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import type { MCPRegistryServerResponse } from "@/lib/api/generated/model";

import { ServerForm } from "../../server-form";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

type EditRegistryServerPageProps = {
  params: Promise<{
    serverName: string[];
  }>;
  searchParams: Promise<{
    version?: string;
  }>;
};

async function getServer(serverName: string, version: string) {
  const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
  const response = await fetch(
    `${backendUrl}/api/v1/mcp/registry/servers/${encodedName}/versions/${encodeURIComponent(version)}`,
    { cache: "no-store" }
  );
  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as MCPRegistryServerResponse;
}

export default async function EditRegistryServerPage({
  params,
  searchParams,
}: EditRegistryServerPageProps) {
  const { serverName } = await params;
  const { version } = await searchParams;
  const decodedName = serverName.map(decodeURIComponent).join("/");
  const selectedVersion = version || "latest";
  const response = await getServer(decodedName, selectedVersion);

  if (!response) {
    notFound();
  }

  return (
    <AppShell active="registry" eyebrow="MCP Registry" title="Edit server">
      <ServerForm initialServer={response.server} mode="edit" />
    </AppShell>
  );
}
