import {
  BookOpen,
  Boxes,
  Activity,
  Gauge,
  Home,
  KeyRound,
  MessageSquare,
  PlugZap,
  Replace,
  ServerCog,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { WorkspaceContext } from "@/lib/workspace-types";

import { BrandMark } from "./brand-mark";
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
      label: "Catalog",
      href: organizationId ? `/org/${organizationId}/catalog` : "/org",
      activeKey: "catalog",
      icon: BookOpen,
    },
    {
      label: "LLM Credentials",
      href: organizationId ? `/org/${organizationId}/llm-credentials` : "/org",
      activeKey: "llm-credentials",
      icon: PlugZap,
    },
    {
      label: "Agent Tokens",
      href: organizationId ? `/org/${organizationId}/tokens` : "/org",
      activeKey: "agent-tokens",
      icon: KeyRound,
    },
    {
      label: "Limits",
      href: organizationId ? `/org/${organizationId}/limits` : "/org",
      activeKey: "limits",
      icon: SlidersHorizontal,
    },
    {
      label: "Secret Backends",
      href: organizationId ? `/org/${organizationId}/secret-backends` : "/org",
      activeKey: "secret-backends",
      icon: ShieldCheck,
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
      label: "Chat",
      href: `${workspaceBasePath}/chat`,
      activeKey: "workspace-chat",
      icon: MessageSquare,
    },
    {
      label: "Dashboard",
      href: `${workspaceBasePath}/dashboard`,
      activeKey: "workspace-dashboard",
      icon: Home,
    },
    {
      label: "MCP Servers",
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
      label: "Observability",
      href: `${workspaceBasePath}/observability`,
      activeKey: "workspace-observability",
      icon: Gauge,
    },
    {
      label: "Guardrails",
      href: `${workspaceBasePath}/guardrails`,
      activeKey: "workspace-guardrails",
      icon: ShieldCheck,
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
    | "workspace-chat"
    | "workspace-observability"
    | "catalog"
    | "llm-credentials"
    | "secret-backends"
    | "workspace-guardrails"
    | "agents"
    | "workspace-agents"
    | "agent-tokens"
    | "limits"
    | "runtime"
    | "install";
  eyebrow: string;
  title: string;
  actions?: ReactNode;
  workspaceContext?: WorkspaceContext;
  sectionClassName?: string;
  contentClassName?: string;
  contentInnerClassName?: string;
  children: ReactNode;
};

export function AppShell({
  active,
  eyebrow,
  title,
  actions,
  workspaceContext,
  sectionClassName,
  contentClassName,
  contentInnerClassName,
  children,
}: AppShellProps) {
  const isWorkspaceScope =
    active === "workspace-dashboard" ||
    active === "workspace-chat" ||
    active === "install" ||
    active === "runtime" ||
    active === "workspace-observability" ||
    active === "workspace-guardrails" ||
    active === "workspace-agents" ||
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
    <main className="min-h-screen bg-background text-foreground">
      <aside className="fixed left-0 top-0 z-50 flex h-screen w-[252px] flex-col border-r border-border bg-sidebar px-3 py-4 text-sidebar-foreground max-lg:static max-lg:h-auto max-lg:w-full max-lg:border-b max-lg:border-r-0 max-lg:px-4 max-lg:py-3">
        <div className="mb-6 px-2 max-lg:mb-3">
          <div className="flex items-center gap-3">
            <BrandMark className="size-8" sizes="32px" />
            <div className="min-w-0">
              <div className="truncate text-[15px] font-semibold leading-5 text-foreground">
                Wardn AI
              </div>
            </div>
          </div>
        </div>

        <nav
          className="flex-1 space-y-1 max-lg:flex max-lg:gap-2 max-lg:space-y-0 max-lg:overflow-x-auto max-lg:pb-1"
          aria-label="Primary"
        >
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                className={cn(
                  "flex min-h-9 items-center gap-2.5 rounded-md px-3 text-sm text-sidebar-foreground transition-colors active:bg-muted max-lg:min-w-fit",
                  "hover:bg-muted hover:text-foreground",
                  item.active &&
                    "border border-[#d9e6ff] bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-[var(--shadow-card)] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
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

        <div className="mt-auto border-t border-border pt-4 max-lg:hidden">
          <Link
            className="flex min-h-9 items-center gap-2.5 rounded-md px-3 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            href={contextSwitchHref}
          >
            <Replace className="size-4" />
            {contextSwitchLabel}
          </Link>
          <div className="mt-3 flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2">
            <div className="flex size-7 items-center justify-center rounded-md border border-border bg-muted text-xs font-semibold text-foreground">
              {contextTitle.slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-foreground">
                {contextTitle}
              </div>
              <div className="truncate text-[11px] text-muted-foreground">
                {contextSubtitle}
              </div>
            </div>
          </div>
        </div>
      </aside>

      <section
        className={cn(
          "min-h-screen min-w-0 bg-background pl-[252px] max-lg:pl-0",
          sectionClassName
        )}
      >
        <header className="fixed right-0 top-0 z-40 flex h-14 w-[calc(100%-252px)] items-center border-b border-border bg-card/95 backdrop-blur max-lg:static max-lg:w-full">
          <div className="flex w-full items-center justify-between gap-4 px-6 max-md:px-4">
            <div className="flex min-w-0 items-center gap-4">
              {showBreadcrumbParent ? (
                <>
                  <span className="truncate text-sm leading-5 text-muted-foreground max-md:hidden">
                    {breadcrumbLabel}
                  </span>
                  <span className="text-sm leading-5 text-muted-foreground max-md:hidden">
                    /
                  </span>
                </>
              ) : null}
              <h1 className="truncate text-lg font-semibold leading-6 text-foreground">
                {title}
              </h1>
            </div>
            <div className="flex items-center gap-2">
              {actions}
              <LogoutButton />
            </div>
          </div>
        </header>

        <div
          className={cn(
            "mx-auto min-h-screen w-full max-w-[1360px] px-6 pb-8 pt-20 max-lg:pt-6 max-md:px-4 max-md:pb-4",
            contentClassName
          )}
        >
          <div className={cn("space-y-6", contentInnerClassName)}>{children}</div>
        </div>
      </section>
    </main>
  );
}
