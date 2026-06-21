import { AppShell } from "@/app/components/app-shell";

import { ServerForm } from "../server-form";

export default function NewRegistryServerPage() {
  return (
    <AppShell active="registry" eyebrow="MCP Registry" title="Add server">
      <ServerForm mode="create" />
    </AppShell>
  );
}
