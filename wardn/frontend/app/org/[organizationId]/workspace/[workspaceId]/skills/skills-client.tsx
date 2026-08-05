"use client";

import {
  Activity,
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Clock,
  ExternalLink,
  History,
  Loader2,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { type FormEvent, type ReactNode, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  AgentSkillActivityRead,
  AgentSkillAgentRead,
  AgentSkillCatalogResponse,
  AgentSkillSearchResultRead,
  WorkspaceApprovedSkillRead,
} from "@/lib/api/generated/model";
import {
  workspaceSkillsApprove,
  workspaceSkillsAssignAgents,
  workspaceSkillsList,
  workspaceSkillsRemove,
  workspaceSkillsSearch,
} from "@/lib/api/generated/workspace-skills/workspace-skills";
import { cn } from "@/lib/utils";

type SkillsClientProps = {
  initialCatalog: AgentSkillCatalogResponse;
  organizationId: string;
  workspaceId: string;
};

type SkillTab = "discover" | "library" | "usage";

const tabs: { id: SkillTab; label: string }[] = [
  { id: "discover", label: "Discover" },
  { id: "library", label: "Workspace Library" },
  { id: "usage", label: "Usage" },
];

function statusVariant(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  if (["pass", "healthy", "connected", "completed", "succeeded"].includes(normalized)) {
    return "success";
  }
  if (["fail", "failed", "unhealthy", "blocked"].includes(normalized)) {
    return "destructive";
  }
  return "secondary";
}

function formatCount(value?: number | null) {
  return new Intl.NumberFormat("en").format(value ?? 0);
}

function formatDate(value?: string | null) {
  if (!value) {
    return "Never";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function runHref(organizationId: string, workspaceId: string, runId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/agent-runs/${encodeURIComponent(runId)}`;
}

function EmptyState({
  action,
  children,
  title,
}: {
  action?: ReactNode;
  children: ReactNode;
  title: string;
}) {
  return (
    <div className="rounded-md border border-dashed border-border bg-muted/20 px-4 py-10 text-center">
      <div className="text-sm font-semibold">{title}</div>
      <div className="mx-auto mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
        {children}
      </div>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

function SkillBadge({
  approved,
  temporary,
}: {
  approved?: boolean | null;
  temporary?: boolean | null;
}) {
  if (approved) {
    return <Badge variant="success">Approved</Badge>;
  }
  if (temporary) {
    return <Badge variant="outline">Hub fallback</Badge>;
  }
  return <Badge variant="secondary">Hub result</Badge>;
}

function ActivityBadge({ activity }: { activity: AgentSkillActivityRead }) {
  if (activity.eventType === "search") {
    return <Badge variant="secondary">Search</Badge>;
  }
  if (activity.eventType === "fetch") {
    return <Badge variant="secondary">Fetch</Badge>;
  }
  if (activity.eventType === "selected") {
    return <Badge variant="outline">Selected</Badge>;
  }
  return <Badge variant="outline">Activity</Badge>;
}

function useApprovedSkillIds(catalog: AgentSkillCatalogResponse) {
  return useMemo(
    () => new Set((catalog.library ?? []).map((skill) => skill.skillId)),
    [catalog.library]
  );
}

export function SkillsClient({
  initialCatalog,
  organizationId,
  workspaceId,
}: SkillsClientProps) {
  const [catalog, setCatalog] = useState(initialCatalog);
  const [activeTab, setActiveTab] = useState<SkillTab>("discover");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AgentSkillSearchResultRead[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [resultCount, setResultCount] = useState<number | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [mutatingId, setMutatingId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const agents = catalog.agents ?? [];
  const library = catalog.library ?? [];
  const recommendations = catalog.recommendations ?? [];
  const workflows = catalog.guidedWorkflows ?? [];
  const recentActivity = catalog.recentActivity ?? [];
  const usage = catalog.usageSummary ?? {};
  const approvedSkillIds = useApprovedSkillIds(catalog);
  const assignedAgentCount = agents.filter(
    (agent) => (agent.assignedApprovedSkillIds ?? []).length > 0
  ).length;

  const previewShortcuts =
    recommendations.length > 0
      ? recommendations.map((recommendation) => ({
          id: recommendation.id,
          query: recommendation.query,
          title: recommendation.title,
        }))
      : workflows.map((workflow) => ({
          id: workflow.id,
          query: workflow.query,
          title: workflow.title,
        }));

  const tabCounts = {
    discover: resultCount ?? 0,
    library: library.length,
    usage: recentActivity.length,
  };

  async function refreshCatalog() {
    const nextCatalog = await workspaceSkillsList(organizationId, workspaceId);
    setCatalog(nextCatalog);
  }

  async function runSearch(nextQuery: string) {
    const normalizedQuery = nextQuery.trim();
    if (normalizedQuery.length < 3) {
      return;
    }
    setQuery(normalizedQuery);
    setIsSearching(true);
    setError("");
    setResultCount(null);
    setHasSearched(true);
    try {
      const payload = await workspaceSkillsSearch(organizationId, workspaceId, {
        query: normalizedQuery,
        limit: 8,
      });
      setResults(payload.results ?? []);
      setResultCount(payload.count ?? 0);
    } catch (caught) {
      setResults([]);
      setResultCount(0);
      setError(caught instanceof Error ? caught.message : "Skill search failed.");
    } finally {
      setIsSearching(false);
    }
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runSearch(query);
  }

  async function approveSkill(result: AgentSkillSearchResultRead) {
    setMutatingId(result.id);
    setError("");
    setNotice("");
    try {
      await workspaceSkillsApprove(organizationId, workspaceId, { skillId: result.id });
      await refreshCatalog();
      setNotice(`${result.name || result.id} is now approved for this workspace.`);
      setActiveTab("library");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not approve skill.");
    } finally {
      setMutatingId("");
    }
  }

  async function removeSkill(skill: WorkspaceApprovedSkillRead) {
    setMutatingId(skill.id);
    setError("");
    setNotice("");
    try {
      await workspaceSkillsRemove(organizationId, workspaceId, skill.id);
      await refreshCatalog();
      setNotice(`${skill.name || skill.skillId} was removed from the workspace library.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not remove skill.");
    } finally {
      setMutatingId("");
    }
  }

  async function toggleAgent(skill: WorkspaceApprovedSkillRead, agent: AgentSkillAgentRead) {
    const currentIds = skill.assignedAgentIds ?? [];
    const assigned = currentIds.includes(agent.id);
    const nextIds = assigned
      ? currentIds.filter((agentId) => agentId !== agent.id)
      : [...currentIds, agent.id];
    setMutatingId(`${skill.id}:${agent.id}`);
    setError("");
    setNotice("");
    try {
      await workspaceSkillsAssignAgents(organizationId, workspaceId, skill.id, {
        agentIds: nextIds,
      });
      await refreshCatalog();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update assignments.");
    } finally {
      setMutatingId("");
    }
  }

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div className="space-y-2">
          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          ) : null}
          {notice ? (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {notice}
            </div>
          ) : null}
        </div>
      )}

      <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 px-4 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Sparkles className="size-4 text-muted-foreground" />
              <h2 className="text-base font-semibold tracking-normal">Skill Marketplace</h2>
              <Badge variant={library.length > 0 ? "success" : "secondary"}>
                {formatCount(library.length)} approved
              </Badge>
            </div>
            <p className="mt-1 max-w-4xl text-sm leading-6 text-muted-foreground">
              Search Wardn Hub, approve trusted guidance into this workspace, assign it to agents,
              and verify usage from run evidence.
            </p>
          </div>
          <div className="grid min-w-72 grid-cols-3 gap-2 text-sm">
            <div className="rounded-md border border-border px-3 py-2">
              <div className="text-xs text-muted-foreground">Library</div>
              <div className="font-semibold">{formatCount(library.length)}</div>
            </div>
            <div className="rounded-md border border-border px-3 py-2">
              <div className="text-xs text-muted-foreground">Agents</div>
              <div className="font-semibold">
                {formatCount(assignedAgentCount)}/{formatCount(agents.length)}
              </div>
            </div>
            <div className="rounded-md border border-border px-3 py-2">
              <div className="text-xs text-muted-foreground">Runs</div>
              <div className="font-semibold">{formatCount(usage.skillRunsLast7d)}</div>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1 border-b border-border/80 bg-muted/30 px-3 py-2">
          {tabs.map((tab) => {
            const selected = activeTab === tab.id;
            return (
              <button
                aria-pressed={selected}
                className={cn(
                  "inline-flex h-8 items-center gap-2 rounded-md border px-3 text-sm transition-colors",
                  selected
                    ? "border-neutral-900 bg-neutral-900 font-medium text-white shadow-[var(--shadow-card)]"
                    : "border-transparent text-muted-foreground hover:bg-card/70 hover:text-foreground"
                )}
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                {tab.label}
                <span
                  className={cn(
                    "rounded-sm border px-1.5 py-0.5 text-[11px] leading-none",
                    selected
                      ? "border-white/20 bg-white/15 text-white"
                      : "border-border bg-muted text-muted-foreground"
                  )}
                >
                  {formatCount(tabCounts[tab.id])}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      {activeTab === "discover" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card>
            <CardHeader>
              <CardTitle>Discover Hub Skills</CardTitle>
              <CardDescription>
                Search with broad catalog terms. Approving a skill adds it to this workspace
                library; agents only prefer approved skills after assignment.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <form className="flex gap-2" onSubmit={submitSearch}>
                <div className="min-w-0 flex-1 space-y-1">
                  <Label className="sr-only" htmlFor="skill-search">
                    Search Wardn Hub skills
                  </Label>
                  <Input
                    id="skill-search"
                    maxLength={120}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="kubernetes ops"
                    value={query}
                  />
                </div>
                <Button
                  disabled={isSearching || query.trim().length < 3}
                  onClick={() => void runSearch(query)}
                  type="button"
                >
                  {isSearching ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Search className="size-4" />
                  )}
                  Search
                </Button>
              </form>

              <div className="flex flex-wrap gap-2">
                {previewShortcuts.slice(0, 6).map((shortcut) => (
                  <Button
                    key={shortcut.id}
                    onClick={() => void runSearch(shortcut.query)}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    {shortcut.title}
                  </Button>
                ))}
              </div>

              {!hasSearched ? (
                <EmptyState title="Start with a domain or workflow">
                  Use terms like Kubernetes ops, GitHub review, SEO, or incident response. The
                  results are Hub records that can become workspace-approved guidance.
                </EmptyState>
              ) : results.length === 0 ? (
                <EmptyState title="No matching skills">
                  Try broader terms. Hub search works best with one to three generic catalog words.
                </EmptyState>
              ) : (
                <div className="grid gap-3">
                  {results.map((result) => {
                    const approved = approvedSkillIds.has(result.id) || result.approved;
                    return (
                      <div className="rounded-md border border-border bg-card p-4" key={result.id}>
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="font-semibold">{result.name || result.id}</div>
                              <SkillBadge approved={approved} temporary={!approved} />
                              <Badge variant={statusVariant(result.auditStatus)}>
                                Audit {result.auditStatus ?? "unknown"}
                              </Badge>
                            </div>
                            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                              {result.description || "No description is available for this skill."}
                            </p>
                            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                              <span>{result.id}</span>
                              {result.sourceName || result.source ? (
                                <span>{result.sourceName || result.source}</span>
                              ) : null}
                            </div>
                          </div>
                          <div className="flex shrink-0 gap-2">
                            {result.url ? (
                              <Button asChild size="icon" title="Open Hub result" variant="outline">
                                <a href={result.url} rel="noreferrer" target="_blank">
                                  <ExternalLink className="size-4" />
                                </a>
                              </Button>
                            ) : null}
                            <Button
                              disabled={approved || mutatingId === result.id}
                              onClick={() => void approveSkill(result)}
                              type="button"
                            >
                              {mutatingId === result.id ? (
                                <Loader2 className="size-4 animate-spin" />
                              ) : (
                                <BookOpenCheck className="size-4" />
                              )}
                              {approved ? "Approved" : "Approve"}
                            </Button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Approval Model</CardTitle>
              <CardDescription>What changes when a skill is approved.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 font-medium">
                  <ShieldCheck className="size-4 text-muted-foreground" />
                  Workspace trust
                </div>
                <p className="mt-1 leading-6 text-muted-foreground">
                  Approved skills are the preferred library for this workspace. They keep audit,
                  hash, source, and assignment metadata.
                </p>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 font-medium">
                  <UserRound className="size-4 text-muted-foreground" />
                  Agent assignment
                </div>
                <p className="mt-1 leading-6 text-muted-foreground">
                  Assign a skill to the agents that should prefer it. Assignment automatically
                  enables the internal skill-search gateway for those agents.
                </p>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 font-medium">
                  <History className="size-4 text-muted-foreground" />
                  Run evidence
                </div>
                <p className="mt-1 leading-6 text-muted-foreground">
                  Usage shows whether a run searched approved guidance or fell back to temporary Hub
                  results.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {activeTab === "library" ? (
        <Card>
          <CardHeader>
            <CardTitle>Workspace Library</CardTitle>
            <CardDescription>
              Approved skills are workspace-level. Assign them to agents that should prefer this
              guidance during runs.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {library.length === 0 ? (
              <EmptyState
                action={
                  <Button onClick={() => setActiveTab("discover")} type="button">
                    Search Hub skills
                    <ArrowRight className="size-4" />
                  </Button>
                }
                title="No approved skills yet"
              >
                Use Discover to search Wardn Hub and approve the first skill into this workspace.
              </EmptyState>
            ) : (
              <div className="grid gap-4">
                {library.map((skill) => (
                  <div className="rounded-md border border-border bg-card" key={skill.id}>
                    <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 p-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="font-semibold">{skill.name || skill.skillId}</div>
                          <Badge variant={statusVariant(skill.auditStatus)}>
                            Audit {skill.auditStatus}
                          </Badge>
                          <Badge variant="secondary">
                            {formatCount(skill.assignedAgentIds?.length ?? 0)} agents
                          </Badge>
                        </div>
                        <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
                          {skill.description || "No description is available for this skill."}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
                          <span>{skill.skillId}</span>
                          {skill.contentHash ? <span>Hash {skill.contentHash}</span> : null}
                          <span>Last used {formatDate(skill.lastUsedAt)}</span>
                        </div>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        {skill.url ? (
                          <Button asChild size="icon" title="Open Hub record" variant="outline">
                            <a href={skill.url} rel="noreferrer" target="_blank">
                              <ExternalLink className="size-4" />
                            </a>
                          </Button>
                        ) : null}
                        <Button
                          disabled={mutatingId === skill.id}
                          onClick={() => void removeSkill(skill)}
                          type="button"
                          variant="outline"
                        >
                          {mutatingId === skill.id ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <Trash2 className="size-4" />
                          )}
                          Remove
                        </Button>
                      </div>
                    </div>
                    <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
                      {agents.length > 0 ? (
                        agents.map((agent) => {
                          const assigned = (skill.assignedAgentIds ?? []).includes(agent.id);
                          const pending = mutatingId === `${skill.id}:${agent.id}`;
                          return (
                            <label
                              className={cn(
                                "flex cursor-pointer items-start gap-3 rounded-md border p-3",
                                assigned
                                  ? "border-emerald-200 bg-emerald-50"
                                  : "border-border bg-card"
                              )}
                              key={agent.id}
                            >
                              <input
                                checked={assigned}
                                className="mt-1 size-4 accent-emerald-700"
                                disabled={pending}
                                onChange={() => void toggleAgent(skill, agent)}
                                type="checkbox"
                              />
                              <span className="min-w-0">
                                <span className="flex items-center gap-2 text-sm font-medium">
                                  {agent.name}
                                  {pending ? <Loader2 className="size-3 animate-spin" /> : null}
                                </span>
                                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                                  {(agent.assignedApprovedSkillIds ?? []).length} assigned skills,
                                  last guidance use {formatDate(agent.lastUsedAt)}
                                </span>
                              </span>
                            </label>
                          );
                        })
                      ) : (
                        <div className="text-sm text-muted-foreground">
                          No workspace agents are available.
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "usage" ? (
        <Card>
          <CardHeader>
            <CardTitle>Usage Evidence</CardTitle>
            <CardDescription>
              Persisted search, fetch, and selection events from agent runs.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Activity className="size-4 text-muted-foreground" />
                  {formatCount(usage.skillEventsLast7d)} events
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  Search, fetch, and selected events in the last 7 days.
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <BookOpenCheck className="size-4 text-muted-foreground" />
                  {formatCount(usage.assignedApprovedSkills)} assignments
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  Agent-to-approved-skill assignments currently configured.
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <CheckCircle2 className="size-4 text-muted-foreground" />
                  {formatCount(usage.failuresLast7d)} failures
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  Failed or blocked skill events in the last 7 days.
                </div>
              </div>
            </div>

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Skill or Query</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-24 text-right">Run</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentActivity.length > 0 ? (
                  recentActivity.map((activity) => (
                    <TableRow key={activity.id}>
                      <TableCell>
                        <div className="flex items-center gap-2 whitespace-nowrap">
                          <Clock className="size-4 text-muted-foreground" />
                          {formatDate(activity.createdAt)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <ActivityBadge activity={activity} />
                      </TableCell>
                      <TableCell>{activity.agentName}</TableCell>
                      <TableCell>
                        <div className="space-y-1">
                          <div className="max-w-lg truncate font-medium">
                            {activity.query ||
                              activity.fetchedSkillId ||
                              activity.skillName ||
                              activity.toolName}
                          </div>
                          <div className="max-w-lg truncate text-xs text-muted-foreground">
                            {activity.summary}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <SkillBadge approved={activity.approved} temporary={activity.temporary} />
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(activity.status)}>
                          {activity.status || "recorded"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button asChild size="icon" title="Open run" variant="outline">
                          <Link
                            aria-label="Open run"
                            href={runHref(organizationId, workspaceId, activity.agentRunId)}
                          >
                            <ArrowRight className="size-4" />
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell className="h-32 text-center text-muted-foreground" colSpan={7}>
                      No skill activity has been recorded in recent runs.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
