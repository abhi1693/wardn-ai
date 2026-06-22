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
    { label: "Overview", href: "/", activeKey: "dashboard", icon: Home },
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
  const workspaceMode = active === "workspace-dashboard" || active === "install";
  const organizationItems = organizationNavItems(workspaceContext);
  const workspaceItems = workspaceNavItems(workspaceContext);
  const selectedOrganization = workspaceContext?.selectedOrganization;

  if (!workspaceMode) {
    return (
      <main className="min-h-screen bg-background">
        <header className="border-b bg-card">
          <div className="flex h-12 items-center justify-between px-4">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex size-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
                W
              </div>
              <div className="min-w-0 text-sm font-semibold">Wardn AI</div>
              {workspaceContext ? (
                <div className="w-72 max-w-[40vw]">
                  <WorkspaceSelector context={workspaceContext} />
                </div>
              ) : null}
              <Link
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                href="/organizations"
              >
                Manage organizations
              </Link>
            </div>
            <div className="flex items-center gap-2">
              {actions}
              <LogoutButton />
            </div>
          </div>
          <nav className="flex h-12 items-end gap-6 px-4" aria-label="Organization">
            <Link
              className={cn(
                "flex h-12 items-center border-b-2 border-transparent text-sm text-muted-foreground transition-colors hover:text-foreground",
                active === "dashboard" && "border-foreground text-foreground"
              )}
              href="/"
            >
              Workspaces
            </Link>
            <Link
              className={cn(
                "flex h-12 items-center border-b-2 border-transparent text-sm text-muted-foreground transition-colors hover:text-foreground",
                active === "registry" && "border-foreground text-foreground"
              )}
              href="/registry"
            >
              Registry
            </Link>
            {selectedOrganization ? (
              <Link
                className={cn(
                  "flex h-12 items-center border-b-2 border-transparent text-sm text-muted-foreground transition-colors hover:text-foreground",
                  active === "organization-settings" && "border-foreground text-foreground"
                )}
                href={`/organizations/${selectedOrganization.id}/settings`}
              >
                Settings
              </Link>
            ) : null}
          </nav>
        </header>

        <section className="mx-auto w-full max-w-6xl px-6 py-8 max-md:px-4">
          <header className="mb-8 flex items-start justify-between gap-4 max-md:flex-col">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-normal text-muted-foreground">
                {selectedOrganization ? selectedOrganization.name : eyebrow}
              </p>
              <h1 className="text-2xl font-semibold tracking-normal text-foreground">{title}</h1>
            </div>
          </header>
          <div className="space-y-6">{children}</div>
        </section>
      </main>
    );
  }

  return (
    <main className="grid min-h-screen grid-cols-[248px_minmax(0,1fr)] bg-background max-lg:grid-cols-1">
      <aside className="flex min-h-screen flex-col border-r bg-card px-3 py-3 max-lg:min-h-0 max-lg:border-r-0 max-lg:border-b">
        <div className="flex h-9 items-center gap-2 px-2">
          <div className="flex size-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
            W
          </div>
          <div className="text-sm font-semibold leading-5">Wardn AI</div>
        </div>

        {workspaceContext ? (
          <div className="mt-4 px-1">
            <WorkspaceSelector context={workspaceContext} />
          </div>
        ) : null}

        <nav className="mt-5 grid gap-6 max-lg:mt-5" aria-label="Primary">
          <div>
            <div className="mb-2 flex items-center justify-between px-3">
              <span className="truncate text-xs font-semibold uppercase tracking-normal text-muted-foreground">
                Workspace
              </span>
              {workspaceContext?.selectedWorkspace ? (
                <Boxes className="size-3.5 text-muted-foreground" />
              ) : null}
            </div>
            {workspaceItems.length > 0 ? (
              <div className="grid gap-1">
                {workspaceItems.map((item) => {
                  const Icon = item.icon;
                  const isActive = item.activeKey === active;
                  const className = cn(
                    "flex min-h-8 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors",
                    isActive && "bg-muted text-foreground",
                    "hover:bg-muted hover:text-foreground"
                  );

                  return (
                    <Link className={className} href={item.href} key={item.label}>
                      <Icon className="size-4" />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed px-3 py-3 text-sm text-muted-foreground">
                Create a workspace to enable MCP navigation.
              </div>
            )}
          </div>

          <div>
            <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              Organization
            </div>
            <div className="grid gap-1">
              {organizationItems.map((item) => {
                const Icon = item.icon;
                const isActive = item.activeKey === active;
                const className = cn(
                  "flex min-h-8 items-center gap-2 rounded-md px-3 text-sm text-muted-foreground transition-colors",
                  isActive && "bg-muted text-foreground",
                  "hover:bg-muted hover:text-foreground"
                );

                return (
                  <Link className={className} href={item.href} key={item.label}>
                    <Icon className="size-4" />
                    {item.label}
                  </Link>
                );
              })}
              <Link
                className="flex min-h-8 items-center gap-2 rounded-md px-3 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                href="/organizations"
              >
                <Building2 className="size-4" />
                Manage
              </Link>
            </div>
          </div>
        </nav>

        <div className="mt-auto max-lg:mt-5" />
      </aside>

      <section className="min-w-0 px-7 py-6 max-md:px-4">
        <header className="mb-6 flex items-start justify-between gap-4 border-b pb-5 max-md:flex-col">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              {selectedOrganization ? selectedOrganization.name : eyebrow}
            </p>
            <h1 className="text-2xl font-semibold tracking-normal text-foreground">{title}</h1>
          </div>
          <div className="flex items-center gap-2 max-md:w-full max-md:flex-wrap">
            {actions}
            <LogoutButton />
          </div>
        </header>
        <div className="space-y-5">{children}</div>
      </section>
    </main>
  );
}
