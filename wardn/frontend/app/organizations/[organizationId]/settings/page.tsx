import { notFound } from "next/navigation";
import {
  BadgeDollarSign,
  BarChart3,
  KeyRound,
  PlugZap,
  Save,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";

import { getWorkspaceContext } from "../../data";
import { OrganizationForm } from "../../organization-form";

type OrganizationSettingsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationSettingsPage({ params }: OrganizationSettingsPageProps) {
  const { organizationId } = await params;
  const formId = "organization-settings-form";
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;
  if (!organization) {
    notFound();
  }
  const organizationBasePath = `/org/${encodeURIComponent(organization.id)}`;
  const adminLinks = [
    {
      description: "Add or rotate model provider credentials used by workspace agents.",
      href: `${organizationBasePath}/llm-credentials`,
      icon: PlugZap,
      title: "LLM Credentials",
    },
    {
      description: "Configure model pricing for usage and cost reporting.",
      href: `${organizationBasePath}/llm-pricing`,
      icon: BadgeDollarSign,
      title: "LLM Pricing",
    },
    {
      description: "Create API tokens for governed agent and gateway access.",
      href: `${organizationBasePath}/tokens`,
      icon: KeyRound,
      title: "Agent Tokens",
    },
    {
      description: "Set organization and workspace quotas.",
      href: `${organizationBasePath}/limits`,
      icon: SlidersHorizontal,
      title: "Limits",
    },
    {
      description: "Manage external stores for secrets and connection credentials.",
      href: `${organizationBasePath}/secret-backends`,
      icon: ShieldCheck,
      title: "Secret Backends",
    },
    {
      description: "Inspect aggregate activity and cost across the organization.",
      href: `${organizationBasePath}/usage`,
      icon: BarChart3,
      title: "Usage",
    },
  ];

  return (
    <AppShell
      active="organization-settings"
      actions={
        <Button form={formId} size="sm" type="submit">
          <Save className="size-4" />
          Save Changes
        </Button>
      }
      eyebrow="Organization"
      title="Settings"
      workspaceContext={workspaceContext}
    >
      <div className="space-y-6">
        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {adminLinks.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] transition-colors hover:border-ring/40 hover:bg-muted/30"
                href={item.href}
                key={item.title}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold">{item.title}</div>
                  <Icon className="size-4 text-muted-foreground" />
                </div>
                <p className="mt-2 text-sm leading-5 text-muted-foreground">
                  {item.description}
                </p>
              </Link>
            );
          })}
        </section>

        <OrganizationForm formId={formId} initialOrganization={organization} mode="edit" />
      </div>
    </AppShell>
  );
}
