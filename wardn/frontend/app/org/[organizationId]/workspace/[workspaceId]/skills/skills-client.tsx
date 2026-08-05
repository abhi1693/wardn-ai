"use client";

import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  Gauge,
  History,
  Loader2,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
  Wrench,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { type FormEvent, useMemo, useState } from "react";

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
} from "@/lib/api/generated/model";
import { workspaceAgentsUpdateSkills } from "@/lib/api/generated/workspace-agents/workspace-agents";
import { workspaceSkillsSearch } from "@/lib/api/generated/workspace-skills/workspace-skills";
import { cn } from "@/lib/utils";

const FIND_SKILLS_SKILL_ID = "abhi1693/wardn-hub/find-skills";

type SkillsClientProps = {
  initialCatalog: AgentSkillCatalogResponse;
  organizationId: string;
  workspaceId: string;
};

type SkillTab = "overview" | "agents" | "discover" | "activity" | "governance";

const tabs: { id: SkillTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "agents", label: "Agents" },
  { id: "discover", label: "Discover" },
  { id: "activity", label: "Activity" },
  { id: "governance", label: "Governance" },
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

function skillEnabled(agent: AgentSkillAgentRead) {
  return (agent.enabledSkillIds ?? []).includes(FIND_SKILLS_SKILL_ID);
}

function normalizeResults(results?: AgentSkillSearchResultRead[]) {
  return results ?? [];
}

function MetricCard({
  description,
  icon: Icon,
  label,
  value,
}: {
  description: string;
  icon: typeof Activity;
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-muted-foreground">{label}</div>
          <Icon className="size-4 text-muted-foreground" />
        </div>
        <div className="mt-2 text-2xl font-semibold tracking-normal">{value}</div>
        <div className="mt-1 text-xs leading-5 text-muted-foreground">{description}</div>
      </CardContent>
    </Card>
  );
}

function EmptyState({ children }: { children: string }) {
  return (
    <div
      className={cn(
        "rounded-md border border-dashed border-border px-4 py-8 text-center",
        "text-sm text-muted-foreground"
      )}
    >
      {children}
    </div>
  );
}

function ActivityBadge({ activity }: { activity: AgentSkillActivityRead }) {
  const eventType = activity.eventType ?? "activity";
  if (eventType === "search") {
    return <Badge variant="secondary">Search</Badge>;
  }
  if (eventType === "fetch") {
    return <Badge variant="secondary">Fetch</Badge>;
  }
  if (eventType === "selected") {
    return <Badge variant="outline">Selected</Badge>;
  }
  return <Badge variant="outline">Activity</Badge>;
}

export function SkillsClient({
  initialCatalog,
  organizationId,
  workspaceId,
}: SkillsClientProps) {
  const [catalog, setCatalog] = useState(initialCatalog);
  const [activeTab, setActiveTab] = useState<SkillTab>("overview");
  const [query, setQuery] = useState("kubernetes ops");
  const [results, setResults] = useState<AgentSkillSearchResultRead[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [updatingAgentId, setUpdatingAgentId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const skills = catalog.skills ?? [];
  const agents = catalog.agents ?? [];
  const recommendations = catalog.recommendations ?? [];
  const workflows = catalog.guidedWorkflows ?? [];
  const recentActivity = catalog.recentActivity ?? [];
  const usage = catalog.usageSummary ?? {};
  const findSkills = skills.find((skill) => skill.id === FIND_SKILLS_SKILL_ID);
  const enabledAgents = agents.filter(skillEnabled);
  const lastUsed = usage.lastUsedAt ?? recentActivity[0]?.createdAt ?? null;

  const tabCounts = useMemo(
    () => ({
      overview: usage.skillEventsLast7d ?? 0,
      agents: enabledAgents.length,
      discover: results.length || recommendations.length,
      activity: recentActivity.length,
      governance: skills.length,
    }),
    [
      enabledAgents.length,
      recentActivity.length,
      recommendations.length,
      results.length,
      skills.length,
      usage.skillEventsLast7d,
    ]
  );

  async function runSearch(nextQuery: string) {
    const normalizedQuery = nextQuery.trim();
    if (normalizedQuery.length < 3) {
      return;
    }
    setActiveTab("discover");
    setQuery(normalizedQuery);
    setIsSearching(true);
    setError("");
    setNotice("");
    try {
      const payload = await workspaceSkillsSearch(organizationId, workspaceId, {
        query: normalizedQuery,
        limit: 8,
      });
      setResults(normalizeResults(payload.results));
      setNotice(`Found ${payload.count ?? 0} matching skill${payload.count === 1 ? "" : "s"}.`);
    } catch (caught) {
      setResults([]);
      setError(caught instanceof Error ? caught.message : "Skill search failed.");
    } finally {
      setIsSearching(false);
    }
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runSearch(query);
  }

  async function toggleAgentSkill(agent: AgentSkillAgentRead, enabled: boolean) {
    const currentSkillIds = agent.enabledSkillIds ?? [];
    const nextSkillIds = enabled
      ? Array.from(new Set([...currentSkillIds, FIND_SKILLS_SKILL_ID]))
      : currentSkillIds.filter((skillId) => skillId !== FIND_SKILLS_SKILL_ID);

    setUpdatingAgentId(agent.id);
    setError("");
    setNotice("");
    try {
      const updatedAgent = await workspaceAgentsUpdateSkills(
        organizationId,
        workspaceId,
        agent.id,
        { skillIds: nextSkillIds }
      );
      setCatalog((current) => {
        const updatedAgents = (current.agents ?? []).map((candidate) =>
          candidate.id === updatedAgent.id ? { ...candidate, ...updatedAgent } : candidate
        );
        const enabledAgentRows = updatedAgents.filter(skillEnabled);
        const updatedSkills = (current.skills ?? []).map((skill) =>
          skill.id === FIND_SKILLS_SKILL_ID
            ? {
                ...skill,
                installed: enabledAgentRows.length > 0,
                enabledAgentIds: enabledAgentRows.map((row) => row.id),
                enabledAgentNames: enabledAgentRows.map((row) => row.name),
              }
            : skill
        );
        return {
          ...current,
          agents: updatedAgents,
          skills: updatedSkills,
          usageSummary: {
            ...current.usageSummary,
            activeSkills: updatedSkills.filter((skill) => skill.installed).length,
            enabledAgents: enabledAgentRows.length,
            totalAgents: updatedAgents.length,
          },
        };
      });
      setNotice(
        enabled
          ? `${updatedAgent.name} can now search Wardn Hub skills.`
          : `${updatedAgent.name} will not use Wardn Hub skill discovery.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update agent skills.");
    } finally {
      setUpdatingAgentId("");
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
            <div
              className={cn(
                "rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2",
                "text-sm text-emerald-700"
              )}
            >
              {notice}
            </div>
          ) : null}
        </div>
      )}

      <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 px-4 py-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Sparkles className="size-4 text-muted-foreground" />
              <h2 className="text-base font-semibold tracking-normal">Skill Operations</h2>
              <Badge variant={enabledAgents.length > 0 ? "success" : "secondary"}>
                {formatCount(enabledAgents.length)} enabled
              </Badge>
            </div>
            <div className="mt-1 text-sm leading-5 text-muted-foreground">
              Configured skills, observed usage, and Wardn Hub discovery in one place.
            </div>
          </div>
          {findSkills?.url ? (
            <Button asChild size="sm" variant="outline">
              <a href={findSkills.url} rel="noreferrer" target="_blank">
                Open Hub
                <ExternalLink className="size-4" />
              </a>
            </Button>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1 border-b border-border/80 bg-muted/30 px-3 py-2">
          {tabs.map((tab) => (
            <button
              className={cn(
                "inline-flex h-8 items-center gap-2 rounded-md px-3 text-sm transition-colors",
                activeTab === tab.id
                  ? "bg-card text-foreground shadow-[var(--shadow-card)]"
                  : "text-muted-foreground hover:bg-card/70 hover:text-foreground"
              )}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              type="button"
            >
              {tab.label}
              <span
                className={cn(
                  "rounded-sm border border-border bg-muted px-1.5 py-0.5",
                  "text-[11px] leading-none text-muted-foreground"
                )}
              >
                {formatCount(tabCounts[tab.id])}
              </span>
            </button>
          ))}
        </div>
      </section>

      {activeTab === "overview" ? (
        <div className="space-y-4">
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              description={`${formatCount(usage.totalAgents ?? agents.length)} workspace agents.`}
              icon={UserRound}
              label="Agents with skills"
              value={`${formatCount(usage.enabledAgents ?? enabledAgents.length)}/${formatCount(
                usage.totalAgents ?? agents.length
              )}`}
            />
            <MetricCard
              description={`${formatCount(usage.skillRunsLast7d)} runs used at least one skill.`}
              icon={Activity}
              label="Skill events"
              value={formatCount(usage.skillEventsLast7d)}
            />
            <MetricCard
              description={`${formatCount(usage.searchesLast7d)} searches, ${formatCount(
                usage.fetchesLast7d
              )} fetches.`}
              icon={Search}
              label="Discovery"
              value={formatCount((usage.searchesLast7d ?? 0) + (usage.fetchesLast7d ?? 0))}
            />
            <MetricCard
              description={`Last observed ${formatDate(lastUsed)}.`}
              icon={Gauge}
              label="Failures"
              value={formatCount(usage.failuresLast7d)}
            />
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card>
              <CardHeader>
                <CardTitle>Installed Capability</CardTitle>
                <CardDescription>
                  Wardn currently exposes audited Hub discovery as the workspace skill capability.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {findSkills ? (
                  <div className="rounded-md border border-border p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold">{findSkills.name}</div>
                        <div className="mt-1 text-sm leading-6 text-muted-foreground">
                          {findSkills.description}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={findSkills.installed ? "success" : "secondary"}>
                          {findSkills.installed ? "Installed" : "Available"}
                        </Badge>
                        <Badge variant={statusVariant(findSkills.auditStatus)}>
                          Audit {findSkills.auditStatus ?? "unknown"}
                        </Badge>
                        <Badge variant={statusVariant(findSkills.healthStatus)}>
                          {findSkills.healthStatus ?? "unknown"}
                        </Badge>
                      </div>
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      {(findSkills.permissions ?? []).map((permission) => (
                        <div className="rounded-md border border-border bg-muted/20 p-3" key={permission.key}>
                          <div className="flex items-center gap-2 text-sm font-medium">
                            <ShieldCheck className="size-4 text-muted-foreground" />
                            {permission.label}
                          </div>
                          <div className="mt-1 text-xs leading-5 text-muted-foreground">
                            {permission.description}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <EmptyState>No skill capability is registered for this workspace.</EmptyState>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Recent Skill Activity</CardTitle>
                <CardDescription>Latest persisted skill events across agent runs.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {recentActivity.length === 0 ? (
                  <EmptyState>No skill activity has been recorded yet.</EmptyState>
                ) : (
                  recentActivity.slice(0, 5).map((activity) => (
                    <div className="rounded-md border border-border p-3" key={activity.id}>
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">
                            {activity.query || activity.fetchedSkillId || activity.toolName}
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {activity.agentName} / {formatDate(activity.createdAt)}
                          </div>
                        </div>
                        <ActivityBadge activity={activity} />
                      </div>
                      <div className="mt-2 flex justify-end">
                        <Button asChild size="sm" variant="outline">
                          <Link href={runHref(organizationId, workspaceId, activity.agentRunId)}>
                            Open run
                            <ArrowRight className="size-4" />
                          </Link>
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </section>
        </div>
      ) : null}

      {activeTab === "agents" ? (
        <Card>
          <CardHeader>
            <CardTitle>Agent Skill Controls</CardTitle>
            <CardDescription>
              Enable discovery where the agent benefits from reusable operational guidance.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Calls 7d</TableHead>
                  <TableHead className="text-right">Search</TableHead>
                  <TableHead className="text-right">Fetch</TableHead>
                  <TableHead>Last used</TableHead>
                  <TableHead className="w-40 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.length > 0 ? (
                  agents.map((agent) => {
                    const enabled = skillEnabled(agent);
                    return (
                      <TableRow key={agent.id}>
                        <TableCell>
                          <div className="space-y-1">
                            <div className="font-medium">{agent.name}</div>
                            <div className="max-w-80 truncate text-xs text-muted-foreground">
                              {(agent.observedSkillIds ?? []).length > 0
                                ? (agent.observedSkillIds ?? []).join(", ")
                                : "No observed skill usage"}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={enabled ? "success" : "secondary"}>
                            {enabled ? "Enabled" : "Disabled"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatCount(agent.callsLast7d)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatCount(agent.searchesLast7d)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatCount(agent.fetchesLast7d)}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span>{formatDate(agent.lastUsedAt)}</span>
                            {agent.recentRunId ? (
                              <Button asChild size="icon" title="Open latest skill run" variant="outline">
                                <Link
                                  aria-label="Open latest skill run"
                                  href={runHref(organizationId, workspaceId, agent.recentRunId)}
                                >
                                  <ArrowRight className="size-4" />
                                </Link>
                              </Button>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            disabled={updatingAgentId === agent.id}
                            onClick={() => void toggleAgentSkill(agent, !enabled)}
                            size="sm"
                            type="button"
                            variant={enabled ? "outline" : "default"}
                          >
                            {updatingAgentId === agent.id ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : enabled ? (
                              <XCircle className="size-4" />
                            ) : (
                              <CheckCircle2 className="size-4" />
                            )}
                            {enabled ? "Disable" : "Enable"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })
                ) : (
                  <TableRow>
                    <TableCell className="h-32 text-center text-muted-foreground" colSpan={7}>
                      No workspace agents are available.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "discover" ? (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <Card>
            <CardHeader>
              <CardTitle>Discover Skills</CardTitle>
              <CardDescription>Search audited public Wardn Hub guidance.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <form className="flex gap-2" onSubmit={submitSearch}>
                <div className="min-w-0 flex-1 space-y-1">
                  <Label className="sr-only" htmlFor="skill-search">
                    Search skills
                  </Label>
                  <Input
                    id="skill-search"
                    maxLength={120}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="kubernetes ops"
                    value={query}
                  />
                </div>
                <Button disabled={isSearching || query.trim().length < 3} type="submit">
                  {isSearching ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Search className="size-4" />
                  )}
                  Search
                </Button>
              </form>

              {results.length === 0 ? (
                <EmptyState>Search results will appear here.</EmptyState>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Skill</TableHead>
                      <TableHead>Source</TableHead>
                      <TableHead>Audit</TableHead>
                      <TableHead className="text-right">Installs</TableHead>
                      <TableHead className="w-24 text-right">Open</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.map((result) => (
                      <TableRow key={result.id}>
                        <TableCell>
                          <div className="space-y-1">
                            <div className="font-medium">{result.name || result.id}</div>
                            <div className="max-w-xl truncate text-xs text-muted-foreground">
                              {result.description}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>{result.source || result.id}</TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(result.auditStatus)}>
                            {result.auditStatus ?? "unknown"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatCount(result.installs)}
                        </TableCell>
                        <TableCell className="text-right">
                          {result.url ? (
                            <Button asChild size="icon" title="Open skill" variant="outline">
                              <a href={result.url} rel="noreferrer" target="_blank">
                                <ExternalLink className="size-4" />
                              </a>
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Recommended Searches</CardTitle>
                <CardDescription>Generated from enabled workspace connections.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {recommendations.length === 0 ? (
                  <EmptyState>No connection-based recommendations are available.</EmptyState>
                ) : (
                  recommendations.map((recommendation) => (
                    <button
                      className={cn(
                        "w-full rounded-md border border-border p-3 text-left",
                        "transition-colors hover:border-neutral-300 hover:bg-muted/40"
                      )}
                      key={recommendation.id}
                      onClick={() => void runSearch(recommendation.query)}
                      type="button"
                    >
                      <div className="text-sm font-medium">{recommendation.title}</div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">
                        {recommendation.description}
                      </div>
                    </button>
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Workflow Starters</CardTitle>
                <CardDescription>Reusable searches for common agent work.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {workflows.map((workflow) => (
                  <button
                    className={cn(
                      "flex w-full items-center justify-between gap-3 rounded-md border",
                      "border-border px-3 py-2 text-left text-sm transition-colors",
                      "hover:border-neutral-300 hover:bg-muted/40"
                    )}
                    key={workflow.id}
                    onClick={() => void runSearch(workflow.query)}
                    type="button"
                  >
                    <span className="min-w-0 truncate">{workflow.title}</span>
                    <Search className="size-4 shrink-0 text-muted-foreground" />
                  </button>
                ))}
              </CardContent>
            </Card>
          </div>
        </section>
      ) : null}

      {activeTab === "activity" ? (
        <Card>
          <CardHeader>
            <CardTitle>Skill Activity</CardTitle>
            <CardDescription>Observed skill events from recent agent run traces.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Query or Skill</TableHead>
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
                    <TableCell className="h-32 text-center text-muted-foreground" colSpan={6}>
                      No skill events have been recorded in recent runs.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "governance" ? (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <Card>
            <CardHeader>
              <CardTitle>Governance</CardTitle>
              <CardDescription>
                Audit, source, and runtime boundary for enabled skill capability.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {skills.map((skill) => (
                <div className="rounded-md border border-border p-4" key={skill.id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium">{skill.name}</div>
                      <div className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                        {skill.description}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Badge variant={statusVariant(skill.auditStatus)}>
                        Audit {skill.auditStatus ?? "unknown"}
                      </Badge>
                      <Badge variant={statusVariant(skill.healthStatus)}>
                        {skill.healthStatus ?? "unknown"}
                      </Badge>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <div className="rounded-md bg-muted/40 p-3">
                      <div className="text-xs font-medium uppercase text-muted-foreground">
                        Source
                      </div>
                      <div className="mt-1 truncate text-sm font-medium">
                        {skill.source || skill.id}
                      </div>
                    </div>
                    <div className="rounded-md bg-muted/40 p-3">
                      <div className="text-xs font-medium uppercase text-muted-foreground">
                        Audit score
                      </div>
                      <div className="mt-1 text-sm font-medium">
                        {skill.auditScore ?? "Unknown"}
                        {skill.auditRank ? ` / ${skill.auditRank}` : ""}
                      </div>
                    </div>
                    <div className="rounded-md bg-muted/40 p-3">
                      <div className="text-xs font-medium uppercase text-muted-foreground">
                        Enabled agents
                      </div>
                      <div className="mt-1 text-sm font-medium">
                        {formatCount(skill.enabledAgentIds?.length)}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Runtime Boundary</CardTitle>
              <CardDescription>
                Skills guide agent behavior; tools still execute through Wardn policy.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Wrench className="size-4 text-muted-foreground" />
                  Tool execution
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  MCP calls remain gated by search_tools, run_tool, and access-rule evaluation.
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <ShieldCheck className="size-4 text-muted-foreground" />
                  Audit status
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  Unsafe skill bundles are rejected before their content reaches the agent.
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <History className="size-4 text-muted-foreground" />
                  Run provenance
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  Skill selections, searches, fetches, and failures are persisted in run traces.
                </div>
              </div>
            </CardContent>
          </Card>
        </section>
      ) : null}
    </div>
  );
}
