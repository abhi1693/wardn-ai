import {
  Activity,
  BadgeDollarSign,
  BookOpen,
  Boxes,
  BarChart3,
  Gauge,
  Home,
  KeyRound,
  ListTree,
  MessageSquare,
  PlugZap,
  Replace,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Webhook,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { WorkspaceContext } from "@/lib/workspace-types";

import { BrandMark } from "./brand-mark";
import { LogoutButton } from "./logout-button";

type AppShellActive =
  | "dashboard"
  | "org-dashboard"
  | "workspaces"
  | "organizations"
  | "organization-settings"
  | "workspace-settings"
  | "workspace-dashboard"
  | "workspace-chat"
  | "workspace-chat-providers"
  | "workspace-runs"
  | "workspace-skills"
  | "workspace-observability"
  | "catalog"
  | "llm-credentials"
  | "llm-pricing"
  | "usage"
  | "secret-backends"
  | "workspace-guardrails"
  | "agent-tokens"
  | "limits"
  | "runtime"
  | "install";

type NavigationItem = {
  activeKey: AppShellActive;
  activeKeys?: AppShellActive[];
  href: string;
  icon: LucideIcon;
  label: string;
};

type NavigationSection = {
  items: NavigationItem[];
  label: string;
};

function organizationNavSections(workspaceContext?: WorkspaceContext): NavigationSection[] {
  const organizationId = workspaceContext?.selectedOrganization?.id;
  const organizationBasePath = organizationId
    ? `/org/${encodeURIComponent(organizationId)}`
    : "/org";
  const organizationSettingsPath = organizationId
    ? `/organizations/${encodeURIComponent(organizationId)}/settings`
    : "/org";
  const sections: NavigationSection[] = [
    {
      label: "Organization",
      items: [
        {
          label: "Dashboard",
          href: organizationId ? `${organizationBasePath}/dashboard` : "/org",
          activeKey: "org-dashboard",
          icon: Home,
        },
        {
          label: "Workspaces",
          href: organizationId ? `${organizationBasePath}/workspaces` : "/org",
          activeKey: "workspaces",
          icon: Boxes,
        },
        {
          label: "Catalog",
          href: organizationId ? `${organizationBasePath}/catalog` : "/org",
          activeKey: "catalog",
          icon: BookOpen,
        },
      ],
    },
  ];

  if (organizationId) {
    sections.push(
      {
        label: "Settings",
        items: [
          {
            label: "Profile",
            href: organizationSettingsPath,
            activeKey: "organization-settings",
            icon: Settings,
          },
          {
            label: "Usage",
            href: `${organizationBasePath}/usage`,
            activeKey: "usage",
            icon: BarChart3,
          },
        ],
      },
      {
        label: "Controls",
        items: [
          {
            label: "LLM Credentials",
            href: `${organizationBasePath}/llm-credentials`,
            activeKey: "llm-credentials",
            icon: PlugZap,
          },
          {
            label: "Model Pricing",
            href: `${organizationBasePath}/llm-pricing`,
            activeKey: "llm-pricing",
            icon: BadgeDollarSign,
          },
          {
            label: "Agent Tokens",
            href: `${organizationBasePath}/tokens`,
            activeKey: "agent-tokens",
            icon: KeyRound,
          },
          {
            label: "Limits",
            href: `${organizationBasePath}/limits`,
            activeKey: "limits",
            icon: SlidersHorizontal,
          },
          {
            label: "Secret Backends",
            href: `${organizationBasePath}/secret-backends`,
            activeKey: "secret-backends",
            icon: ShieldCheck,
          },
        ],
      }
    );
  }

  return sections;
}

function workspaceNavSections(workspaceContext?: WorkspaceContext): NavigationSection[] {
  const organizationId = workspaceContext?.selectedOrganization?.id;
  const workspaceId = workspaceContext?.selectedWorkspace?.id;
  if (!organizationId || !workspaceId) {
    return organizationNavSections(workspaceContext);
  }

  const workspaceBasePath = `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}`;

  return [
    {
      label: "Workspace",
      items: [
        {
          label: "Dashboard",
          href: `${workspaceBasePath}/dashboard`,
          activeKey: "workspace-dashboard",
          icon: Home,
        },
        {
          label: "Chat",
          href: `${workspaceBasePath}/chat`,
          activeKey: "workspace-chat",
          icon: MessageSquare,
        },
        {
          label: "Providers",
          href: `${workspaceBasePath}/chat-providers`,
          activeKey: "workspace-chat-providers",
          icon: Webhook,
        },
        {
          label: "Connections",
          href: `${workspaceBasePath}/install`,
          activeKey: "install",
          icon: PlugZap,
        },
        {
          label: "Skills",
          href: `${workspaceBasePath}/skills`,
          activeKey: "workspace-skills",
          icon: Sparkles,
        },
        {
          label: "Access",
          href: `${workspaceBasePath}/guardrails`,
          activeKey: "workspace-guardrails",
          icon: ShieldCheck,
        },
        {
          label: "Runs",
          href: `${workspaceBasePath}/agent-runs`,
          activeKey: "workspace-runs",
          icon: ListTree,
        },
      ],
    },
    {
      label: "Manage",
      items: [
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
          label: "Settings",
          href: `/organizations/${encodeURIComponent(
            organizationId
          )}/workspaces/${encodeURIComponent(workspaceId)}/settings`,
          activeKey: "workspace-settings",
          icon: Settings,
        },
      ],
    },
    {
      label: "Organization",
      items: [
        {
          label: "Admin",
          href: `/organizations/${encodeURIComponent(organizationId)}/settings`,
          activeKey: "organization-settings",
          activeKeys: [
            "llm-credentials",
            "llm-pricing",
            "usage",
            "agent-tokens",
            "limits",
            "secret-backends",
          ],
          icon: Settings,
        },
      ],
    },
  ];
}

type AppShellProps = {
  active: AppShellActive;
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
    active === "workspace-chat-providers" ||
    active === "workspace-runs" ||
    active === "workspace-skills" ||
    active === "install" ||
    active === "runtime" ||
    active === "workspace-observability" ||
    active === "workspace-guardrails" ||
    active === "workspace-settings";
  const navigationSections = isWorkspaceScope
    ? workspaceNavSections(workspaceContext)
    : organizationNavSections(workspaceContext);
  const selectedOrganization = workspaceContext?.selectedOrganization;
  const selectedWorkspace = workspaceContext?.selectedWorkspace;
  const primaryNavSections = navigationSections.map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      active: item.activeKey === active || item.activeKeys?.includes(active),
    })),
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
      <aside className="fixed left-0 top-0 z-50 flex h-screen w-[260px] flex-col border-r border-border bg-sidebar px-3 py-4 text-sidebar-foreground max-lg:static max-lg:h-auto max-lg:w-full max-lg:overflow-hidden max-lg:border-b max-lg:border-r-0 max-lg:px-4 max-lg:py-3">
        <div className="mb-5 px-2 max-lg:mb-3">
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
          className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1 max-lg:flex max-lg:max-w-full max-lg:gap-2 max-lg:space-y-0 max-lg:overflow-x-auto max-lg:overflow-y-hidden max-lg:pb-1 max-lg:pr-0"
          aria-label="Primary"
        >
          {primaryNavSections.map((section, sectionIndex) => (
            <div
              className="space-y-1 max-lg:flex max-lg:min-w-fit max-lg:gap-2 max-lg:space-y-0"
              key={section.label}
            >
              <div
                className={cn(
                  "px-3 pb-1 text-[11px] font-semibold uppercase tracking-normal text-muted-foreground max-lg:hidden",
                  sectionIndex === 0 ? "pt-0" : "pt-1"
                )}
              >
                {section.label}
              </div>
              {section.items.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    className={cn(
                      "relative flex min-h-9 items-center gap-2.5 rounded-md px-3 text-sm text-sidebar-foreground transition-colors active:bg-muted max-lg:min-w-fit",
                      "hover:bg-muted hover:text-foreground",
                      item.active &&
                        "border border-[#d9e6ff] bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-[var(--shadow-card)] before:absolute before:left-1 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-full before:bg-ring before:content-[''] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                    )}
                    href={item.href}
                    key={item.label}
                  >
                    <Icon className="size-4" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="mt-auto border-t border-border pt-4 max-lg:hidden">
          <Link
            className="flex min-h-9 items-center gap-2.5 rounded-md px-3 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            href={contextSwitchHref}
          >
            <Replace className="size-4" />
            {contextSwitchLabel}
          </Link>
          <div className="mt-3 flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]">
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
          "min-h-screen min-w-0 bg-background pl-[260px] max-lg:pl-0",
          sectionClassName
        )}
      >
        <header className="fixed right-0 top-0 z-40 flex h-14 w-[calc(100%-260px)] items-center border-b border-border bg-card/90 backdrop-blur max-lg:static max-lg:w-full">
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
