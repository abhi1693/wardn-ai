"use client";

import { ArrowLeft, Loader2, Save, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  GuardrailPolicyCreate,
  GuardrailPolicyRead,
  GuardrailPolicyUpdate,
  OrganizationRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";

import { errorMessage } from "../../../tokens/token-form";
import type {
  GuardrailServerOption,
  GuardrailToolOption,
} from "./data";

type GuardrailMode = "allow" | "deny" | "require_confirmation";
type ToolScope = "all" | "selected";

type GuardrailFormProps = {
  basePath: string;
  organization: OrganizationRead;
  policy?: GuardrailPolicyRead;
  servers: GuardrailServerOption[];
  tools: GuardrailToolOption[];
  workspace: WorkspaceRead;
};

const noneValue = "__none__";

const modeOptions: Array<{
  value: GuardrailMode;
  label: string;
  description: string;
}> = [
  {
    value: "deny",
    label: "Deny",
    description: "Block matching MCP tool calls before runtime execution.",
  },
  {
    value: "require_confirmation",
    label: "Require confirmation",
    description: "Pause matching tool calls until an approval flow is available.",
  },
  {
    value: "allow",
    label: "Allow",
    description: "Record an explicit allow policy for audit and future default-deny modes.",
  },
];

function policyEndpoint(organizationId: string, workspaceId: string, policy?: GuardrailPolicyRead) {
  return `/api/organizations/${encodeURIComponent(
    organizationId
  )}/workspaces/${encodeURIComponent(
    workspaceId
  )}/guardrails/policies${policy ? `/${encodeURIComponent(policy.id)}` : ""}`;
}

function selectedValue(value?: string | null) {
  return value && value.length > 0 ? value : noneValue;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function selectedToolIdsFromPolicy(policy?: GuardrailPolicyRead): string[] {
  const conditions = policy?.conditions;
  if (isRecord(conditions)) {
    const rawRules = Array.isArray(conditions.rules) ? conditions.rules : [];
    const selectedToolIds = rawRules
      .filter(isRecord)
      .filter((rule) =>
        rule.field === "tool_schema_id" &&
        rule.operator === "equals" &&
        typeof rule.value === "string"
      )
      .map((rule) => rule.value as string);
    const inRuleToolIds = rawRules
      .filter(isRecord)
      .filter(
        (rule) =>
          rule.field === "tool_schema_id" &&
          rule.operator === "in" &&
          Array.isArray(rule.value)
      )
      .flatMap((rule) =>
        (rule.value as unknown[])
          .filter((value): value is string => typeof value === "string")
      );
    return [...new Set([...selectedToolIds, ...inRuleToolIds])];
  }

  return [];
}

export function GuardrailForm({
  basePath,
  organization,
  policy,
  servers,
  tools,
  workspace,
}: GuardrailFormProps) {
  const router = useRouter();
  const isEditing = Boolean(policy);
  const [name, setName] = useState(policy?.name ?? "");
  const [description, setDescription] = useState(policy?.description ?? "");
  const [mode, setMode] = useState<GuardrailMode>((policy?.mode as GuardrailMode) ?? "deny");
  const [priority, setPriority] = useState(String(policy?.priority ?? 100));
  const initialSelectedToolIds = useMemo(() => selectedToolIdsFromPolicy(policy), [policy]);
  const [toolScope, setToolScope] = useState<ToolScope>(
    initialSelectedToolIds.length > 0 ? "selected" : "all"
  );
  const [selectedToolIds, setSelectedToolIds] = useState<string[]>(initialSelectedToolIds);
  const [serverFilterId, setServerFilterId] = useState("");
  const [isActive, setIsActive] = useState(policy?.isActive ?? true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const workspaceServers = useMemo(
    () => servers.filter((server) => server.workspaceId === workspace.id),
    [servers, workspace.id]
  );
  const workspaceTools = useMemo(
    () => tools.filter((tool) => tool.workspaceId === workspace.id),
    [tools, workspace.id]
  );
  const filteredWorkspaceTools = useMemo(
    () =>
      workspaceTools.filter(
        (tool) => !serverFilterId || tool.installationId === serverFilterId
      ),
    [serverFilterId, workspaceTools]
  );
  const filteredSelectedCount = filteredWorkspaceTools.filter((tool) =>
    selectedToolIds.includes(tool.toolSchemaId)
  ).length;
  const canSave =
    name.trim().length > 0 &&
    !isSubmitting &&
    Number.isFinite(Number(priority)) &&
    Number(priority) >= 0 &&
    (toolScope === "all" || selectedToolIds.length > 0);

  function toggleTool(toolSchemaId: string) {
    setSelectedToolIds((current) =>
      current.includes(toolSchemaId)
        ? current.filter((id) => id !== toolSchemaId)
        : [...current, toolSchemaId]
    );
  }

  function conditionsPayload() {
    if (toolScope === "all") {
      return {};
    }
    return {
      operator: "any",
      rules: selectedToolIds.map((toolSchemaId) => ({
        field: "tool_schema_id",
        operator: "equals",
        value: toolSchemaId,
      })),
    };
  }

  async function submitPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const payload: GuardrailPolicyCreate | GuardrailPolicyUpdate = {
        name: name.trim(),
        description: description.trim(),
        mode,
        priority: Number(priority),
        isActive,
        conditions: conditionsPayload(),
      };

      const response = await fetch(
        policyEndpoint(organization.id, workspace.id, policy),
        {
          method: isEditing ? "PATCH" : "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(errorMessage(data, "Guardrail policy could not be saved."));
      }
      router.push(basePath);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Guardrail policy could not be saved."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="mx-auto max-w-4xl">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle>{isEditing ? "Edit Guardrail Policy" : "Create Guardrail Policy"}</CardTitle>
            <CardDescription>
              Apply policy before any client executes workspace tools.
            </CardDescription>
          </div>
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
            <ShieldCheck className="size-5" />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={submitPolicy}>
          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="guardrail-name">Name</Label>
              <Input
                id="guardrail-name"
                maxLength={120}
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="guardrail-mode">Mode</Label>
              <Select onValueChange={(value) => setMode(value as GuardrailMode)} value={mode}>
                <SelectTrigger id="guardrail-mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {modeOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="guardrail-description">Description</Label>
            <textarea
              className="min-h-20 w-full rounded-[var(--radius)] border border-input bg-card px-3 py-2 text-sm shadow-[var(--shadow-card)] outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
              id="guardrail-description"
              maxLength={500}
              onChange={(event) => setDescription(event.target.value)}
              value={description}
            />
          </div>

          <div className="space-y-4">
            <Label>Applies to</Label>
            <div className="grid gap-3 md:grid-cols-2">
              <button
                className={`rounded-[var(--radius)] border px-4 py-3 text-left shadow-[var(--shadow-card)] transition ${
                  toolScope === "all"
                    ? "border-primary bg-primary/5"
                    : "border-[var(--outline-variant)] bg-card hover:border-primary/50"
                }`}
                onClick={() => setToolScope("all")}
                type="button"
              >
                <span className="block text-sm font-semibold">All tools</span>
                <span className="mt-1 block text-sm text-[var(--on-surface-variant)]">
                  Apply this policy to every tool call.
                </span>
              </button>
              <button
                className={`rounded-[var(--radius)] border px-4 py-3 text-left shadow-[var(--shadow-card)] transition ${
                  toolScope === "selected"
                    ? "border-primary bg-primary/5"
                    : "border-[var(--outline-variant)] bg-card hover:border-primary/50"
                }`}
                onClick={() => setToolScope("selected")}
                type="button"
              >
                <span className="block text-sm font-semibold">Selected tools</span>
                <span className="mt-1 block text-sm text-[var(--on-surface-variant)]">
                  {selectedToolIds.length} selected
                </span>
              </button>
            </div>
          </div>

          {toolScope === "selected" ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div className="space-y-2">
                  <Label htmlFor="guardrail-tool-filter">Tool list</Label>
                  <Select
                    onValueChange={(value) => setServerFilterId(value === noneValue ? "" : value)}
                    value={selectedValue(serverFilterId)}
                  >
                    <SelectTrigger id="guardrail-tool-filter" className="w-72">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={noneValue}>All MCP servers</SelectItem>
                      {workspaceServers.map((server) => (
                        <SelectItem key={server.installationId} value={server.installationId}>
                          {server.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-[var(--on-surface-variant)]">
                    {filteredSelectedCount} of {filteredWorkspaceTools.length} visible selected
                  </span>
                  <Button
                    onClick={() =>
                      setSelectedToolIds((current) => [
                        ...new Set([
                          ...current,
                          ...filteredWorkspaceTools.map((tool) => tool.toolSchemaId),
                        ]),
                      ])
                    }
                    type="button"
                    variant="outline"
                  >
                    Select visible
                  </Button>
                  <Button
                    onClick={() => setSelectedToolIds([])}
                    type="button"
                    variant="outline"
                  >
                    Clear
                  </Button>
                </div>
              </div>

              <div className="max-h-72 overflow-auto rounded-[var(--radius)] border border-[var(--outline-variant)] bg-white">
                {filteredWorkspaceTools.length > 0 ? (
                  filteredWorkspaceTools.map((tool) => (
                    <label
                      className="flex cursor-pointer items-start gap-3 border-b border-[var(--outline-variant)] px-3 py-3 last:border-b-0 hover:bg-[var(--surface-container-low)]"
                      key={tool.toolSchemaId}
                    >
                      <input
                        checked={selectedToolIds.includes(tool.toolSchemaId)}
                        className="mt-0.5 size-4 accent-primary"
                        onChange={() => toggleTool(tool.toolSchemaId)}
                        type="checkbox"
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{tool.toolName}</span>
                        <span className="block truncate text-xs text-[var(--on-surface-variant)]">
                          {tool.configName}
                        </span>
                      </span>
                    </label>
                  ))
                ) : (
                  <div className="px-3 py-6 text-sm text-[var(--on-surface-variant)]">
                    No tools match this filter.
                  </div>
                )}
              </div>

              {selectedToolIds.length === 0 ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  Select at least one tool or switch to all tools.
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="guardrail-priority">Priority</Label>
              <Input
                id="guardrail-priority"
                min={0}
                onChange={(event) => setPriority(event.target.value)}
                type="number"
                value={priority}
              />
            </div>
            <label className="flex min-h-9 items-center gap-3 self-end rounded-[var(--radius)] border border-input bg-card px-3 text-sm shadow-[var(--shadow-card)]">
              <input
                checked={isActive}
                className="size-4 accent-primary"
                onChange={(event) => setIsActive(event.target.checked)}
                type="checkbox"
              />
              Active
            </label>
          </div>

          <div className="flex justify-end gap-2">
            <Button asChild type="button" variant="outline">
              <Link href={basePath}>
                <ArrowLeft className="size-4" />
                Back
              </Link>
            </Button>
            <Button disabled={!canSave} type="submit">
              {isSubmitting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Save className="size-4" />
              )}
              {isEditing ? "Save policy" : "Create policy"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
