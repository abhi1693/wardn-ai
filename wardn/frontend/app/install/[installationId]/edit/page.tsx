import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import type {
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";

import { InstallFormClient } from "../../install-form-client";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

type EditInstallPageProps = {
  params: Promise<{
    installationId: string;
  }>;
};

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

export default async function EditInstallPage({ params }: EditInstallPageProps) {
  const { installationId } = await params;
  const installations = await getInitialInstallations();
  const installation: MCPServerInstallationRead | undefined = installations.find(
    (item) => item.id === installationId
  );

  if (!installation) {
    notFound();
  }

  return (
    <AppShell active="install" eyebrow="MCP Runtime" title="Edit MCP server">
      <InstallFormClient
        initialInstallation={installation}
        initialInstallations={installations}
      />
    </AppShell>
  );
}
