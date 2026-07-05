"use client";

import { ArrowLeft, Loader2, Save, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
  GuardrailAgentOption,
  GuardrailServerOption,
  GuardrailToolOption,
} from "./data";

type GuardrailMode = "allow" | "deny" | "require_confirmation";

type GuardrailFormProps = {
  agents: GuardrailAgentOption[];
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

function modeLabel(mode: GuardrailMode) {
  return modeOptions.find((option) => option.value === mode)?.label ?? mode;
}

function selectedValue(value?: string | null) {
  return value && value.length > 0 ? value : noneValue;
}

export function GuardrailForm({
  agents,
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
  const [agentId, setAgentId] = useState(policy?.agentId ?? "");
  const [installationId, setInstallationId] = useState(policy?.installationId ?? "");
  const [toolSchemaId, setToolSchemaId] = useState(policy?.toolSchemaId ?? "");
  const [isActive, setIsActive] = useState(policy?.isActive ?? true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const workspaceAgents = useMemo(
    () => agents.filter((agent) => agent.workspaceId === workspace.id),
    [agents, workspace.id]
  );
  const workspaceServers = useMemo(
    () => servers.filter((server) => server.workspaceId === workspace.id),
    [servers, workspace.id]
  );
  const workspaceTools = useMemo(
    () =>
      tools.filter(
        (tool) =>
          tool.workspaceId === workspace.id &&
          (!installationId || tool.installationId === installationId)
      ),
    [installationId, tools, workspace.id]
  );
  const selectedTool = tools.find((tool) => tool.toolSchemaId === toolSchemaId);
  const canSave =
    name.trim().length > 0 &&
    !isSubmitting &&
    Number.isFinite(Number(priority)) &&
    Number(priority) >= 0;

  function changeInstallation(value: string) {
    const nextInstallationId = value === noneValue ? "" : value;
    setInstallationId(nextInstallationId);
    setToolSchemaId("");
  }

  function changeTool(value: string) {
    const nextToolSchemaId = value === noneValue ? "" : value;
    setToolSchemaId(nextToolSchemaId);
    const nextTool = tools.find((tool) => tool.toolSchemaId === nextToolSchemaId);
    if (nextTool) {
      setInstallationId(nextTool.installationId);
    }
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
        agentId: agentId || null,
        installationId: selectedTool?.installationId || installationId || null,
        toolSchemaId: toolSchemaId || null,
        conditions: {},
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
              Apply policy before agents execute MCP tools.
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

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="guardrail-agent">Agent</Label>
              <Select
                onValueChange={(value) => setAgentId(value === noneValue ? "" : value)}
                value={selectedValue(agentId)}
              >
                <SelectTrigger id="guardrail-agent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={noneValue}>All agents</SelectItem>
                  {workspaceAgents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="guardrail-server">MCP server</Label>
              <Select
                onValueChange={changeInstallation}
                value={selectedValue(installationId)}
              >
                <SelectTrigger id="guardrail-server">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={noneValue}>All servers</SelectItem>
                  {workspaceServers.map((server) => (
                    <SelectItem key={server.installationId} value={server.installationId}>
                      {server.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="guardrail-tool">Tool</Label>
              <Select onValueChange={changeTool} value={selectedValue(toolSchemaId)}>
                <SelectTrigger id="guardrail-tool">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={noneValue}>All tools</SelectItem>
                  {workspaceTools.map((tool) => (
                    <SelectItem key={tool.toolSchemaId} value={tool.toolSchemaId}>
                      {tool.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

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

          <div className="rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4">
            <div className="mb-2 flex items-center gap-2">
              <Badge variant="outline">{modeLabel(mode)}</Badge>
              <Badge variant="secondary">Workspace</Badge>
            </div>
            <p className="text-sm leading-5 text-[var(--on-surface-variant)]">
              {modeOptions.find((option) => option.value === mode)?.description}
            </p>
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
