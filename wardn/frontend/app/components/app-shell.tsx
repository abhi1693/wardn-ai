import {
  Building2,
  BookOpen,
  Boxes,
  Home,
  Settings,
  ServerCog,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { workspaceBasePath } from "@/lib/workspace-context";
import type { WorkspaceContext } from "@/lib/workspace-types";

import { LogoutButton } from "./logout-button";
import { WorkspaceSelector } from "./workspace-selector";

function organizationNavItems(workspaceContext?: WorkspaceContext) {
  const organizationId = workspaceContext?.selectedOrganization?.id;
  return [
    {
      label: "Workspaces",
      href: organizationId ? `/org/${organizationId}/workspaces` : "/org",
      activeKey: "dashboard",
      icon: Home,
    },
    { label: "Registry", href: "/registry", activeKey: "registry", icon: BookOpen },
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
  if (!workspaceContext?.selectedWorkspace) {
    return [];
  }
  const basePath = workspaceBasePath(workspaceContext);
  return [
    {
      label: "Overview",
      href: `${basePath}/dashboard`,
      activeKey: "workspace-dashboard",
      icon: Home,
    },
    {
      label: "Installations",
      href: `${basePath}/install`,
      activeKey: "install",
      icon: ServerCog,
    },
  ];
}

type AppShellProps = {
  active:
    | "dashboard"
    | "organizations"
    | "organization-settings"
    | "workspace-dashboard"
    | "registry"
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
  const organizationItems = organizationNavItems(workspaceContext);
  const workspaceItems = workspaceNavItems(workspaceContext);
  const selectedOrganization = workspaceContext?.selectedOrganization;
  const navGroups = [
    {
      label: "Workspace",
      items: workspaceItems,
      icon: workspaceContext?.selectedWorkspace ? Boxes : undefined,
      empty: "Create a workspace to enable MCP navigation.",
    },
    {
      label: "Organization",
      items: organizationItems,
    },
  ];

  return (
    <main className="grid min-h-screen grid-cols-[260px_minmax(0,1fr)] bg-background max-lg:grid-cols-1">
      <aside className="flex min-h-screen flex-col border-r border-slate-800 bg-sidebar px-3 py-4 text-sidebar-foreground max-lg:min-h-0 max-lg:border-r-0 max-lg:border-b max-lg:border-slate-800">
        <div className="flex h-10 items-center gap-2 px-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-white text-xs font-bold text-slate-950">
            W
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold leading-5 text-white">Wardn AI</div>
            <div className="text-[11px] font-medium leading-4 text-slate-400">Control plane</div>
          </div>
        </div>

        {workspaceContext ? (
          <div className="mt-4 px-1">
            <WorkspaceSelector context={workspaceContext} />
          </div>
        ) : null}

        <nav className="mt-6 grid gap-6 max-lg:mt-4 max-lg:grid-cols-2 max-md:grid-cols-1" aria-label="Primary">
          {navGroups.map((group) => {
            const GroupIcon = group.icon;
            return (
              <div key={group.label}>
                <div className="mb-2 flex items-center justify-between px-3">
                  <span className="truncate text-[11px] font-semibold uppercase leading-4 tracking-[0.08em] text-slate-400">
                    {group.label}
                  </span>
                  {GroupIcon ? <GroupIcon className="size-3.5 text-slate-500" /> : null}
                </div>
                {group.items.length > 0 ? (
                  <div className="grid gap-1">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const isActive = item.activeKey === active;
                      const className = cn(
                        "relative flex min-h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-slate-300 transition-colors hover:bg-sidebar-accent hover:text-white",
                        isActive &&
                          "bg-sidebar-accent text-sidebar-accent-foreground before:absolute before:left-0 before:top-1.5 before:h-6 before:w-0.5 before:rounded-full before:bg-sky-400"
                      );

                      return (
                        <Link className={className} href={item.href} key={item.label}>
                          <Icon className="size-4" />
                          <span>{item.label}</span>
                        </Link>
                      );
                    })}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-slate-700 px-3 py-3 text-sm text-slate-400">
                    {group.empty}
                  </div>
                )}
              </div>
            );
          })}

          <div>
            <div className="mb-2 px-3 text-[11px] font-semibold uppercase leading-4 tracking-[0.08em] text-slate-400">
              Admin
            </div>
            <Link
              className={cn(
                "relative flex min-h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-slate-300 transition-colors hover:bg-sidebar-accent hover:text-white",
                active === "organizations" &&
                  "bg-sidebar-accent text-sidebar-accent-foreground before:absolute before:left-0 before:top-1.5 before:h-6 before:w-0.5 before:rounded-full before:bg-sky-400"
              )}
              href="/organizations"
            >
              <Building2 className="size-4" />
              Manage organizations
            </Link>
          </div>
        </nav>

        <div className="mt-auto border-t border-slate-800 pt-4 max-lg:mt-5">
          <div className="px-3 text-xs leading-5 text-slate-400">
            {selectedOrganization ? selectedOrganization.name : "No organization selected"}
          </div>
        </div>
      </aside>

      <section className="min-w-0 bg-background">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-border bg-card/95 px-8 backdrop-blur max-md:h-auto max-md:min-h-16 max-md:flex-col max-md:items-start max-md:px-4 max-md:py-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase leading-4 tracking-[0.08em] text-muted-foreground">
              {selectedOrganization ? selectedOrganization.name : eyebrow}
            </p>
            <h1 className="truncate text-2xl font-semibold leading-8 tracking-normal text-foreground max-md:text-xl">
              {title}
            </h1>
          </div>
          <div className="flex items-center gap-2 max-md:w-full max-md:flex-wrap">
            {actions}
            <LogoutButton />
          </div>
        </header>

        <div className="mx-auto w-full max-w-[1440px] px-8 py-7 max-md:px-4 max-md:py-5">
          <div className="space-y-6">{children}</div>
        </div>
      </section>
    </main>
  );
}
