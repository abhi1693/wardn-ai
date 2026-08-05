"use client";

import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  History,
  Loader2,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { type FormEvent, type ReactNode, useState } from "react";

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

type SkillTab = "overview" | "agents" | "evidence";

const tabs: { id: SkillTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "agents", label: "Agents" },
  { id: "evidence", label: "Run Evidence" },
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

function formatUnitCount(value: number, singular: string, plural = `${singular}s`) {
  return `${formatCount(value)} ${value === 1 ? singular : plural}`;
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
  icon: LucideIcon;
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
    return <Badge variant="success">Fetched</Badge>;
  }
  if (eventType === "selected") {
    return <Badge variant="outline">Selected</Badge>;
  }
  return <Badge variant="outline">Activity</Badge>;
}

function ActionCard({
  action,
  children,
  icon: Icon,
  title,
}: {
  action?: ReactNode;
  children: ReactNode;
  icon: LucideIcon;
  title: string;
}) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <Icon className="size-4" />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold">{title}</div>
            <div className="mt-1 text-sm leading-6 text-muted-foreground">{children}</div>
          </div>
        </div>
        {action}
      </div>
    </div>
  );
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
  const [hasSearched, setHasSearched] = useState(false);
  const [resultCount, setResultCount] = useState<number | null>(null);
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
  const disabledAgents = agents.filter((agent) => !skillEnabled(agent));
  const unusedEnabledAgents = enabledAgents.filter((agent) => (agent.callsLast7d ?? 0) === 0);
  const lastUsed = usage.lastUsedAt ?? recentActivity[0]?.createdAt ?? null;

  const previewShortcuts =
    recommendations.length > 0
      ? recommendations.map((recommendation) => ({
          description: recommendation.description,
          id: recommendation.id,
          query: recommendation.query,
          title: recommendation.title,
        }))
      : workflows.map((workflow) => ({
          description: workflow.description,
          id: workflow.id,
          query: workflow.query,
          title: workflow.title,
        }));

  const tabCounts = {
    overview: usage.skillRunsLast7d ?? 0,
    agents: enabledAgents.length,
    evidence: recentActivity.length,
  };

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
      setResults(normalizeResults(payload.results));
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
          ? `${updatedAgent.name} can now search Wardn Hub guidance during runs.`
          : `${updatedAgent.name} will not search Wardn Hub guidance during runs.`
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
              <h2 className="text-base font-semibold tracking-normal">Agent Skill Guidance</h2>
              <Badge variant={enabledAgents.length > 0 ? "success" : "secondary"}>
                {formatCount(enabledAgents.length)} of {formatCount(agents.length)} agents enabled
              </Badge>
            </div>
            <div className="mt-1 max-w-4xl text-sm leading-5 text-muted-foreground">
              Wardn currently has one runtime skill capability: Find Skills. It lets enabled agents
              search Wardn Hub for vetted guidance during a run, then records whether that actually
              happened.
            </div>
          </div>
          {findSkills?.url ? (
            <Button asChild size="sm" variant="outline">
              <a href={findSkills.url} rel="noreferrer" target="_blank">
                Open Hub record
                <ExternalLink className="size-4" />
              </a>
            </Button>
          ) : null}
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

      {activeTab === "overview" ? (
        <div className="space-y-4">
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              description="Coverage decides which agents are allowed to retrieve Hub guidance."
              icon={UserRound}
              label="Skill coverage"
              value={`${formatCount(enabledAgents.length)}/${formatCount(agents.length)}`}
            />
            <MetricCard
              description="If this is zero, enabled agents have not needed or chosen skill guidance."
              icon={Activity}
              label="Runs using guidance"
              value={formatCount(usage.skillRunsLast7d)}
            />
            <MetricCard
              description="Searches find candidates; fetches load selected guidance into the run."
              icon={Search}
              label="Search and fetch"
              value={`${formatCount(usage.searchesLast7d)} / ${formatCount(usage.fetchesLast7d)}`}
            />
            <MetricCard
              description={`Last observed use: ${formatDate(lastUsed)}.`}
              icon={ShieldCheck}
              label="Skill issues"
              value={formatCount(usage.failuresLast7d)}
            />
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card>
              <CardHeader>
                <CardTitle>What Needs Attention</CardTitle>
                <CardDescription>
                  Actions are based on current coverage and observed run evidence.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {disabledAgents.length > 0 ? (
                  <ActionCard
                    action={
                      <Button onClick={() => setActiveTab("agents")} size="sm" type="button">
                        Review agents
                        <ArrowRight className="size-4" />
                      </Button>
                    }
                    icon={UserRound}
                    title={`${formatUnitCount(disabledAgents.length, "agent")} cannot use Hub guidance`}
                  >
                    Enable Find Skills only for agents that handle specialist work such as
                    Kubernetes, SEO, observability, marketing, or troubleshooting.
                  </ActionCard>
                ) : (
                  <ActionCard icon={CheckCircle2} title="All agents can use Hub guidance">
                    Coverage is complete. Use run evidence to confirm whether agents are actually
                    searching when specialized work appears.
                  </ActionCard>
                )}

                {enabledAgents.length > 0 && unusedEnabledAgents.length > 0 ? (
                  <ActionCard
                    action={
                      <Button onClick={() => setActiveTab("agents")} size="sm" type="button" variant="outline">
                        View agents
                      </Button>
                    }
                    icon={History}
                    title={`${formatUnitCount(
                      unusedEnabledAgents.length,
                      "enabled agent",
                      "enabled agents"
                    )} ${unusedEnabledAgents.length === 1 ? "has" : "have"} no recent usage`}
                  >
                    This is fine for general agents. For specialist agents, tune their instructions
                    to search Wardn Hub before starting unfamiliar domain work.
                  </ActionCard>
                ) : null}

                {(usage.failuresLast7d ?? 0) > 0 ? (
                  <ActionCard
                    action={
                      <Button onClick={() => setActiveTab("evidence")} size="sm" type="button" variant="outline">
                        Open evidence
                      </Button>
                    }
                    icon={XCircle}
                    title={`${formatUnitCount(
                      usage.failuresLast7d ?? 0,
                      "skill failure",
                      "skill failures"
                    )} in the last 7 days`}
                  >
                    Open the affected runs to see whether discovery failed, a bundle could not be
                    fetched, or the agent selected guidance that was not usable.
                  </ActionCard>
                ) : (
                  <ActionCard icon={ShieldCheck} title="No recent skill failures">
                    The skill gateway is not showing errors in recent persisted run traces.
                  </ActionCard>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>How It Works</CardTitle>
                <CardDescription>Find Skills is a gateway, not a separate app catalog.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-md border border-border p-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <UserRound className="size-4 text-muted-foreground" />
                    Enable on the right agents
                  </div>
                  <div className="mt-1 text-xs leading-5 text-muted-foreground">
                    Disabled agents will never call Find Skills, even if the prompt asks for it.
                  </div>
                </div>
                <div className="rounded-md border border-border p-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Search className="size-4 text-muted-foreground" />
                    Search and fetch during runs
                  </div>
                  <div className="mt-1 text-xs leading-5 text-muted-foreground">
                    A search means the agent looked for guidance; a fetch means it loaded a specific
                    skill bundle into context.
                  </div>
                </div>
                <div className="rounded-md border border-border p-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Wrench className="size-4 text-muted-foreground" />
                    Tool policy still applies
                  </div>
                  <div className="mt-1 text-xs leading-5 text-muted-foreground">
                    Skills guide behavior. MCP tool execution still goes through Wardn access rules.
                  </div>
                </div>
              </CardContent>
            </Card>
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card>
              <CardHeader>
                <CardTitle>Preview Hub Guidance</CardTitle>
                <CardDescription>
                  Check whether useful guidance exists before editing an agent or scheduled task.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <form className="flex gap-2" onSubmit={submitSearch}>
                  <div className="min-w-0 flex-1 space-y-1">
                    <Label className="sr-only" htmlFor="skill-search">
                      Search Wardn Hub guidance
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
                    Preview
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

                {hasSearched && resultCount !== null ? (
                  <div className="text-xs text-muted-foreground">
                    {formatUnitCount(resultCount, "Hub result")} for &quot;{query}&quot;.
                  </div>
                ) : null}

                {!hasSearched ? (
                  <EmptyState>
                    Search results will show whether an enabled agent has useful guidance to fetch.
                  </EmptyState>
                ) : results.length === 0 ? (
                  <EmptyState>No matching Hub guidance was found for this query.</EmptyState>
                ) : (
                  <div className="space-y-3">
                    {results.map((result) => (
                      <div className="rounded-md border border-border p-3" key={result.id}>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="font-medium">{result.name || result.id}</div>
                            <div className="mt-1 max-w-2xl text-sm leading-5 text-muted-foreground">
                              {result.description}
                            </div>
                            <div className="mt-2 flex flex-wrap gap-2">
                              <Badge variant={statusVariant(result.auditStatus)}>
                                Audit {result.auditStatus ?? "unknown"}
                              </Badge>
                              {result.isOfficial ? <Badge variant="success">Official</Badge> : null}
                              <Badge variant="secondary">{result.sourceName || result.source}</Badge>
                            </div>
                          </div>
                          {result.url ? (
                            <Button asChild size="icon" title="Open Hub result" variant="outline">
                              <a href={result.url} rel="noreferrer" target="_blank">
                                <ExternalLink className="size-4" />
                              </a>
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Recent Evidence</CardTitle>
                <CardDescription>Latest runs where Find Skills left a trace.</CardDescription>
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
            <CardTitle>Agent Controls</CardTitle>
            <CardDescription>
              Choose which agents are allowed to search Wardn Hub guidance during runs.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Hub guidance</TableHead>
                  <TableHead>Last 7 days</TableHead>
                  <TableHead>Last evidence</TableHead>
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
                            <div className="max-w-96 truncate text-xs text-muted-foreground">
                              {(agent.observedSkillIds ?? []).length > 0
                                ? `Observed: ${(agent.observedSkillIds ?? []).join(", ")}`
                                : "No observed skill usage"}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={enabled ? "success" : "secondary"}>
                            {enabled ? "Allowed" : "Blocked"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm">
                            {formatCount(agent.callsLast7d)} calls
                            <span className="text-muted-foreground">
                              {" "}
                              / {formatCount(agent.searchesLast7d)} searches /{" "}
                              {formatCount(agent.fetchesLast7d)} fetches
                            </span>
                          </div>
                          {(agent.failuresLast7d ?? 0) > 0 ? (
                            <div className="mt-1 text-xs text-red-600">
                              {formatCount(agent.failuresLast7d)} failures
                            </div>
                          ) : null}
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
                    <TableCell className="h-32 text-center text-muted-foreground" colSpan={5}>
                      No workspace agents are available.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "evidence" ? (
        <Card>
          <CardHeader>
            <CardTitle>Run Evidence</CardTitle>
            <CardDescription>
              Actual search, fetch, and selection events persisted from agent run traces.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-md border border-border p-3">
                <div className="text-sm font-medium">Search</div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  The agent looked for relevant Wardn Hub guidance.
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="text-sm font-medium">Fetched</div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  The agent loaded a specific skill bundle into context.
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="text-sm font-medium">Selected</div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  The agent considered a candidate before continuing the run.
                </div>
              </div>
            </div>

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
    </div>
  );
}
