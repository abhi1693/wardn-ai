import {
  BookOpen,
  Boxes,
  Activity,
  Bot,
  Home,
  KeyRound,
  Layers3,
  PlugZap,
  Replace,
  ServerCog,
  Settings,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { WorkspaceContext } from "@/lib/workspace-types";

import { LogoutButton } from "./logout-button";

function organizationNavItems(workspaceContext?: WorkspaceContext) {
  const organizationId = workspaceContext?.selectedOrganization?.id;
  return [
    {
      label: "Dashboard",
      href: organizationId ? `/org/${organizationId}/dashboard` : "/org",
      activeKey: "org-dashboard",
      icon: Home,
    },
    {
      label: "Workspaces",
      href: organizationId ? `/org/${organizationId}/workspaces` : "/org",
      activeKey: "workspaces",
      icon: Boxes,
    },
    {
      label: "Registry",
      href: organizationId ? `/org/${organizationId}/registry` : "/org",
      activeKey: "registry",
      icon: BookOpen,
    },
    {
      label: "LLM Credentials",
      href: organizationId ? `/org/${organizationId}/llm-credentials` : "/org",
      activeKey: "llm-credentials",
      icon: PlugZap,
    },
    {
      label: "Agents",
      href: organizationId ? `/org/${organizationId}/agents` : "/org",
      activeKey: "agents",
      icon: Bot,
    },
    {
      label: "Agent Tokens",
      href: organizationId ? `/org/${organizationId}/tokens` : "/org",
      activeKey: "agent-tokens",
      icon: KeyRound,
    },
    ...(organizationId
      ? [
          {
            label: "Settings",
            href: `/organizations/${organizationId}/settings`,
            activeKey: "organization-settings",
            icon: Settings,
          },
        ]
      : []),
  ];
}

function workspaceNavItems(workspaceContext?: WorkspaceContext) {
  const organizationId = workspaceContext?.selectedOrganization?.id;
  const workspaceId = workspaceContext?.selectedWorkspace?.id;
  if (!organizationId || !workspaceId) {
    return organizationNavItems(workspaceContext);
  }

  const workspaceBasePath = `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}`;

  return [
    {
      label: "Dashboard",
      href: `${workspaceBasePath}/dashboard`,
      activeKey: "workspace-dashboard",
      icon: Home,
    },
    {
      label: "Installations",
      href: `${workspaceBasePath}/install`,
      activeKey: "install",
      icon: ServerCog,
    },
    {
      label: "Runtime",
      href: `${workspaceBasePath}/runtime`,
      activeKey: "runtime",
      icon: Activity,
    },
    {
      label: "Settings",
      href: `/organizations/${encodeURIComponent(
        organizationId
      )}/workspaces/${encodeURIComponent(workspaceId)}/settings`,
      activeKey: "workspace-settings",
      icon: Settings,
    },
  ];
}

type AppShellProps = {
  active:
    | "dashboard"
    | "org-dashboard"
    | "workspaces"
    | "organizations"
    | "organization-settings"
    | "workspace-settings"
    | "workspace-dashboard"
    | "registry"
    | "llm-credentials"
    | "agents"
    | "agent-tokens"
    | "runtime"
    | "install";
  eyebrow: string;
  title: string;
  actions?: ReactNode;
  workspaceContext?: WorkspaceContext;
  children: ReactNode;
};

export function AppShell({
  active,
  eyebrow,
  title,
  actions,
  workspaceContext,
  children,
}: AppShellProps) {
  const isWorkspaceScope =
    active === "workspace-dashboard" ||
    active === "install" ||
    active === "runtime" ||
    active === "workspace-settings";
  const navigationItems = isWorkspaceScope
    ? workspaceNavItems(workspaceContext)
    : organizationNavItems(workspaceContext);
  const selectedOrganization = workspaceContext?.selectedOrganization;
  const selectedWorkspace = workspaceContext?.selectedWorkspace;
  const primaryNavItems = navigationItems.map((item) => ({
    ...item,
    active: item.activeKey === active,
  }));
  const breadcrumbLabel = selectedOrganization?.name ?? eyebrow;
  const showBreadcrumbParent = breadcrumbLabel !== title;
  const contextSwitchHref =
    isWorkspaceScope && selectedOrganization
      ? `/org/${encodeURIComponent(selectedOrganization.id)}/workspaces`
      : "/org";
  const contextSwitchLabel = isWorkspaceScope ? "Change workspace" : "Change organization";
  const contextTitle =
    isWorkspaceScope
      ? selectedWorkspace?.name ?? selectedOrganization?.name ?? "No workspace"
      : selectedOrganization?.name ?? "No organization";
  const contextSubtitle =
    isWorkspaceScope
      ? selectedOrganization?.name ?? "Workspace context"
      : selectedWorkspace?.name ?? "Organization context";

  return (
    <main className="min-h-screen bg-[var(--surface)] text-foreground">
      <aside className="fixed left-0 top-0 z-50 flex h-screen w-[260px] flex-col border-r border-[var(--on-primary-container)]/20 bg-[var(--primary-container)] px-4 py-6 text-[var(--inverse-on-surface)] max-lg:static max-lg:h-auto max-lg:w-full max-lg:border-b max-lg:border-r-0">
        <div className="mb-10 px-2">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--primary-fixed-dim)] text-[var(--primary-container)]">
              <Layers3 className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-xl font-semibold leading-7 text-white">
                Wardn AI
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-2" aria-label="Primary">
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                className={cn(
                  "flex min-h-11 items-center gap-3 rounded-lg px-4 text-sm text-slate-300 transition-all duration-200 active:scale-[0.98] hover:bg-white/10 hover:text-white",
                  item.active &&
                    "bg-[#d5e3fd] font-semibold text-[#131b2e] hover:bg-[#d5e3fd] hover:text-[#131b2e]"
                )}
                href={item.href}
                key={item.label}
              >
                <Icon className="size-4" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-[var(--on-primary-container)]/10 pt-6 max-lg:mt-6">
          <Link
            className="flex min-h-11 items-center gap-3 rounded-lg px-4 text-sm text-slate-300 transition-all duration-200 active:scale-[0.98] hover:bg-white/10 hover:text-white"
            href={contextSwitchHref}
          >
            <Replace className="size-4" />
            {contextSwitchLabel}
          </Link>
          <div className="mt-4 flex items-center gap-3 px-4">
            <div className="flex size-8 items-center justify-center rounded-full border border-[var(--on-primary-container)]/20 bg-[var(--tertiary-container)] text-xs font-bold text-[var(--on-tertiary)]">
              {contextTitle.slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate text-xs font-bold text-[var(--inverse-on-surface)]">
                {contextTitle}
              </div>
              <div className="truncate text-[10px] text-slate-400">
                {contextSubtitle}
              </div>
            </div>
          </div>
        </div>
      </aside>

      <section className="min-h-screen min-w-0 bg-[var(--surface-bright)] pl-[260px] max-lg:pl-0">
        <header className="fixed right-0 top-0 z-40 flex h-16 w-[calc(100%-260px)] items-center border-b border-[var(--outline-variant)] bg-[var(--surface)] max-lg:static max-lg:w-full">
          <div className="flex w-full items-center justify-between gap-4 px-8 max-md:px-4">
            <div className="flex min-w-0 items-center gap-4">
              {showBreadcrumbParent ? (
                <>
                  <span className="truncate text-sm font-medium leading-5 text-[var(--on-surface-variant)]">
                    {breadcrumbLabel}
                  </span>
                  <span className="text-sm leading-5 text-[var(--on-surface-variant)]">/</span>
                </>
              ) : null}
              <h1 className="truncate text-xl font-bold leading-7 text-[var(--on-surface)]">
                {title}
              </h1>
            </div>
            <div className="flex items-center gap-2">
              {actions}
              <LogoutButton />
            </div>
          </div>
        </header>

        <div className="mx-auto min-h-screen w-full max-w-[1440px] px-8 pb-8 pt-24 max-lg:pt-8 max-md:px-4 max-md:pb-4">
          <div className="space-y-6">{children}</div>
        </div>
      </section>
    </main>
  );
}
