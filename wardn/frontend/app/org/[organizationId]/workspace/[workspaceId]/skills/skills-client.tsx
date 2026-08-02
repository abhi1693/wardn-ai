"use client";

import {
  ExternalLink,
  Loader2,
  Search,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
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
import type {
  AgentSkillCatalogResponse,
  AgentSkillSearchResultRead,
} from "@/lib/api/generated/model";
import {
  workspaceSkillsSearch,
} from "@/lib/api/generated/workspace-skills/workspace-skills";
import { cn } from "@/lib/utils";

const FIND_SKILLS_SKILL_ID = "abhi1693/wardn-hub/find-skills";

type SkillsClientProps = {
  initialCatalog: AgentSkillCatalogResponse;
  organizationId: string;
  workspaceId: string;
};

function statusVariant(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  if (["pass", "healthy", "connected"].includes(normalized)) {
    return "success";
  }
  if (["fail", "failed", "unhealthy", "blocked"].includes(normalized)) {
    return "destructive";
  }
  return "secondary";
}

function normalizeResults(results?: AgentSkillSearchResultRead[]) {
  return results ?? [];
}

export function SkillsClient({
  initialCatalog,
  organizationId,
  workspaceId,
}: SkillsClientProps) {
  const catalog = initialCatalog;
  const [query, setQuery] = useState("kubernetes ops");
  const [results, setResults] = useState<AgentSkillSearchResultRead[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const findSkills = catalog.skills?.find((skill) => skill.id === FIND_SKILLS_SKILL_ID);
  const agents = catalog.agents ?? [];
  const assistant = agents[0];
  const recommendations = catalog.recommendations ?? [];
  const workflows = catalog.guidedWorkflows ?? [];
  const installedAgentIds = useMemo(
    () => new Set(findSkills?.enabledAgentIds ?? []),
    [findSkills?.enabledAgentIds]
  );
  const assistantHasSkillDiscovery = assistant ? installedAgentIds.has(assistant.id) : false;

  async function runSearch(nextQuery: string) {
    const normalizedQuery = nextQuery.trim();
    if (!normalizedQuery) {
      return;
    }
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

  return (
    <div className="space-y-6">
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

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 space-y-1">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Sparkles className="size-4" />
                  Wardn Hub Skills
                </CardTitle>
                <CardDescription>{findSkills?.description}</CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant={findSkills?.installed ? "success" : "secondary"}>
                  {findSkills?.installed ? "Installed" : "Available"}
                </Badge>
                <Badge variant={statusVariant(findSkills?.auditStatus)}>
                  Audit {findSkills?.auditStatus ?? "unknown"}
                </Badge>
                <Badge variant={statusVariant(findSkills?.healthStatus)}>
                  {findSkills?.healthStatus ?? "unknown"}
                </Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-md border border-border bg-muted/30 p-3">
                <div className="text-xs font-medium uppercase text-muted-foreground">
                  Source
                </div>
                <div className="mt-1 flex min-w-0 items-center gap-2 text-sm">
                  <span className="truncate font-medium">
                    {findSkills?.source ?? "Wardn Hub"}
                  </span>
                  {findSkills?.url ? (
                    <Button asChild size="icon" variant="outline">
                      <a href={findSkills.url} rel="noreferrer" target="_blank">
                        <ExternalLink className="size-4" />
                      </a>
                    </Button>
                  ) : null}
                </div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 p-3">
                <div className="text-xs font-medium uppercase text-muted-foreground">
                  Runtime Boundary
                </div>
                <div className="mt-1 text-sm text-foreground">
                  Skills guide workflow selection; MCP tool calls still use access rules.
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">Permissions</div>
              <div className="grid gap-2 md:grid-cols-3">
                {(findSkills?.permissions ?? []).map((permission) => (
                  <div className="rounded-md border border-border p-3" key={permission.key}>
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

            <div className="space-y-2">
              <div className="text-sm font-medium">Workspace assistant</div>
              <div className="rounded-md border border-border px-3 py-3">
                {assistant ? (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{assistant.name}</div>
                      <div className="text-xs text-muted-foreground">
                        Skill discovery is part of workspace chat.
                      </div>
                    </div>
                    <Badge variant={assistantHasSkillDiscovery ? "success" : "secondary"}>
                      {assistantHasSkillDiscovery ? "Enabled" : "Pending"}
                    </Badge>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    Start Chat to create the workspace assistant.
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Search className="size-4" />
              Skill Search
            </CardTitle>
            <CardDescription>
              Public Wardn Hub results are temporary guidance until installed.
            </CardDescription>
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

            <div className="space-y-2">
              {results.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
                  Search for a workflow such as Kubernetes ops, email triage, search console,
                  or GitHub review.
                </div>
              ) : (
                results.map((result) => (
                  <div className="rounded-md border border-border p-3" key={result.id}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{result.name}</div>
                        <div className="truncate text-xs text-muted-foreground">
                          {result.source || result.id}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={result.installed ? "success" : "secondary"}>
                          {result.installed ? "Installed" : "Temporary"}
                        </Badge>
                        <Badge variant={statusVariant(result.auditStatus)}>
                          Audit {result.auditStatus ?? "unknown"}
                        </Badge>
                      </div>
                    </div>
                    <div className="mt-2 line-clamp-2 text-sm text-muted-foreground">
                      {result.description}
                    </div>
                    {result.url ? (
                      <Button asChild className="mt-3" size="sm" variant="outline">
                        <a href={result.url} rel="noreferrer" target="_blank">
                          Open
                          <ExternalLink className="size-4" />
                        </a>
                      </Button>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recommended Skills</CardTitle>
            <CardDescription>Based on installed workspace connections.</CardDescription>
          </CardHeader>
          <CardContent>
            {recommendations.length === 0 ? (
              <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
                Add Connections to populate recommendations.
              </div>
            ) : (
              <div className="space-y-3">
                {recommendations.map((recommendation) => (
                  <div className="rounded-md border border-border p-3" key={recommendation.id}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium">{recommendation.title}</div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {recommendation.description}
                        </div>
                      </div>
                      <Button
                        onClick={() => void runSearch(recommendation.query)}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        <Search className="size-4" />
                        Search
                      </Button>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(recommendation.connectionNames ?? []).map((name) => (
                        <Badge key={name} variant="outline">
                          {name}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Guided Workflows</CardTitle>
            <CardDescription>Starter workflows that can search matching skill guidance.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            {workflows.map((workflow) => (
              <button
                className={cn(
                  "rounded-md border border-border p-3 text-left transition-colors",
                  "hover:border-neutral-300 hover:bg-muted/40"
                )}
                key={workflow.id}
                onClick={() => void runSearch(workflow.query)}
                type="button"
              >
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Workflow className="size-4 text-muted-foreground" />
                  {workflow.title}
                </div>
                <div className="mt-1 text-sm leading-5 text-muted-foreground">
                  {workflow.description}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(workflow.requiredConnectionHints ?? []).map((hint) => (
                    <Badge key={hint} variant="secondary">
                      {hint}
                    </Badge>
                  ))}
                </div>
              </button>
            ))}
          </CardContent>
        </Card>
      </section>

    </div>
  );
}
