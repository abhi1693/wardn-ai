"use client";

import {
  BarChart3,
  CalendarClock,
  CheckCircle2,
  MessageSquare,
  Search,
  Settings,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { StatusDot } from "@/components/atoms/status-dot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";
import { setSelectionCookie } from "@/lib/selection-cookies";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type OrganizationWorkspacesListProps = {
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

type WorkspaceFilter = "active" | "all" | "archived" | "guarded";

function filterLabel(filter: WorkspaceFilter) {
  if (filter === "all") {
    return "All";
  }
  if (filter === "archived") {
    return "Archived";
  }
  if (filter === "guarded") {
    return "Guarded";
  }
  return "Active";
}

function workspacePath(organizationId: string, workspaceId: string, suffix = "/chat") {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}${suffix}`;
}

function workspaceSettingsPath(organizationId: string, workspaceId: string) {
  return `/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
    workspaceId
  )}/settings`;
}

function displayDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(date);
}

function workspaceMatchesFilter(workspace: WorkspaceRead, filter: WorkspaceFilter) {
  if (filter === "all") {
    return true;
  }
  if (filter === "archived") {
    return workspace.status !== "active";
  }
  if (filter === "guarded") {
    return workspace.guardrailDefaultDeny;
  }
  return workspace.status === "active";
}

function workspaceTone(workspace: WorkspaceRead) {
  if (workspace.status !== "active") {
    return "neutral" as const;
  }
  return workspace.guardrailDefaultDeny ? ("success" as const) : ("warning" as const);
}

function statusLabel(workspace: WorkspaceRead) {
  return workspace.status === "active" ? "Active" : "Archived";
}

export function OrganizationWorkspacesList({
  organization,
  workspaces,
}: OrganizationWorkspacesListProps) {
  const router = useRouter();
  const [filter, setFilter] = useState<WorkspaceFilter>("active");
  const [search, setSearch] = useState("");

  const filteredWorkspaces = useMemo(() => {
    const query = search.trim().toLowerCase();
    return workspaces
      .filter((workspace) => {
        const matchesQuery =
          !query ||
          workspace.name.toLowerCase().includes(query) ||
          workspace.slug.toLowerCase().includes(query) ||
          workspace.description.toLowerCase().includes(query);
        return matchesQuery && workspaceMatchesFilter(workspace, filter);
      })
      .sort((first, second) => {
        if (first.status !== second.status) {
          return first.status === "active" ? -1 : 1;
        }
        return first.name.localeCompare(second.name);
      });
  }, [filter, search, workspaces]);

  const activeCount = workspaces.filter((workspace) => workspace.status === "active").length;
  const archivedCount = workspaces.length - activeCount;
  const guardedCount = workspaces.filter((workspace) => workspace.guardrailDefaultDeny).length;
  const summaryItems = [
    { label: "total", value: workspaces.length },
    { label: "active", value: activeCount },
    { label: "archived", value: archivedCount },
    { label: "guarded", value: guardedCount },
  ];

  function setWorkspaceContext(workspaceId: string) {
    setSelectionCookie(selectedOrganizationCookie, organization.id);
    setSelectionCookie(selectedWorkspaceCookie, workspaceId);
  }

  function openWorkspace(workspace: WorkspaceRead) {
    setWorkspaceContext(workspace.id);
    router.push(workspacePath(organization.id, workspace.id));
    router.refresh();
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold leading-5 text-foreground">Workspaces</div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
            {summaryItems.map((item) => (
              <span
                className="inline-flex h-6 items-center gap-1 rounded-sm border border-border bg-muted/60 px-2"
                key={item.label}
              >
                <span className="font-semibold text-foreground">
                  {item.value.toLocaleString("en-US")}
                </span>
                {item.label}
              </span>
            ))}
          </div>
        </div>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative min-w-0 sm:w-[320px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search workspaces"
              type="search"
              value={search}
            />
          </div>
          <div className="flex rounded-md border border-border bg-card p-1">
            {(["active", "guarded", "archived", "all"] as WorkspaceFilter[]).map((item) => (
              <Button
                className="h-7 px-2 text-xs"
                key={item}
                onClick={() => setFilter(item)}
                size="sm"
                type="button"
                variant={filter === item ? "secondary" : "ghost"}
              >
                {filterLabel(item)}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {filteredWorkspaces.length === 0 ? (
        <Card className="flex min-h-60 flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="flex size-10 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
            <Search className="size-5" />
          </div>
          <div>
            <div className="font-medium text-foreground">No workspaces in view</div>
            <div className="mt-1 text-sm text-muted-foreground">No matching workspace records.</div>
          </div>
          <Button asChild size="sm" variant="outline">
            <Link href={`/organizations/${encodeURIComponent(organization.id)}/workspaces/new`}>
              New workspace
            </Link>
          </Button>
        </Card>
      ) : (
        <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredWorkspaces.map((workspace) => {
            const tone = workspaceTone(workspace);
            return (
              <Card
                className="flex min-h-[248px] flex-col overflow-hidden transition-colors hover:border-ring/40 hover:bg-muted/20"
                key={workspace.id}
              >
                <CardHeader className="border-b-0 pb-0">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <StatusDot tone={tone} />
                        <h3 className="truncate text-sm font-semibold leading-5 text-foreground">
                          {workspace.name}
                        </h3>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge variant={workspace.status === "active" ? "success" : "secondary"}>
                          {statusLabel(workspace)}
                        </Badge>
                        <Badge variant="outline">{workspace.currentUserRole}</Badge>
                      </div>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="flex flex-1 flex-col p-4 pt-3">
                  <p className="min-h-10 text-sm leading-5 text-muted-foreground">
                    {workspace.description || workspace.slug}
                  </p>

                  <div className="mt-4 grid gap-3 border-y border-border/80 py-3">
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <ShieldCheck className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Access mode</div>
                        <div className="truncate text-sm font-medium">
                          {workspace.guardrailDefaultDeny ? "Default deny" : "Default allow"}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <CalendarClock className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Updated</div>
                        <div className="truncate text-sm font-medium">
                          {displayDate(workspace.updatedAt)}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <CheckCircle2 className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Slug</div>
                        <div className="truncate text-sm font-medium">{workspace.slug}</div>
                      </div>
                    </div>
                  </div>

                  <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
                    <Button onClick={() => openWorkspace(workspace)} size="sm" type="button">
                      <MessageSquare className="size-4" />
                      Chat
                    </Button>
                    <Button asChild size="sm" variant="outline">
                      <Link
                        href={workspacePath(organization.id, workspace.id, "/dashboard")}
                        onClick={() => setWorkspaceContext(workspace.id)}
                      >
                        <BarChart3 className="size-4" />
                        Dashboard
                      </Link>
                    </Button>
                    <Button asChild className="sm:ml-auto" size="sm" variant="ghost">
                      <Link href={workspaceSettingsPath(organization.id, workspace.id)}>
                        <Settings className="size-4" />
                        Settings
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
