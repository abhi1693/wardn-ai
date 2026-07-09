import { UserRound } from "lucide-react";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import {
  type UsageSummaryResponse,
  UsageSummaryView,
} from "@/app/components/usage-summary-view";
import { getOrganization } from "@/app/organizations/data";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { backendCookieHeader, backendPath, getWorkspaceContext } from "@/lib/workspace-context";

type MyUsagePageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getMyUsage() {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(backendPath("/api/v1/me/usage"), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as UsageSummaryResponse;
  } catch {
    return null;
  }
}

export default async function MyUsagePage({ params }: MyUsagePageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, usage] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getMyUsage(),
  ]);

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="my-usage"
      eyebrow="Organization"
      title="My Usage"
      workspaceContext={workspaceContext}
    >
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <UserRound className="size-4" />
        Your attributed model requests, tokens, cost, and tool calls
      </div>

      {usage ? (
        <UsageSummaryView mode="me" usage={usage} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Usage unavailable</CardTitle>
            <CardDescription>Your usage summary could not be loaded.</CardDescription>
          </CardHeader>
        </Card>
      )}
    </AppShell>
  );
}
