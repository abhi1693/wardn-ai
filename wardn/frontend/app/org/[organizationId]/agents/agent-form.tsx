"use client";

import { Bot, Check, Loader2 } from "lucide-react";
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
import type { AgentRead, OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

import type { LlmCredentialRead } from "../llm-credentials/types";
import { errorMessage } from "../tokens/token-form";

type AgentScope = "organization" | "workspace";

type AgentPayload = {
  name: string;
  description: string;
  instructions: string;
  scope: AgentScope;
  workspaceId?: string | null;
  providerCredentialId?: string | null;
  modelName: string;
  isActive?: boolean;
};

type AgentFormProps = {
  agent?: AgentRead;
  credentials: LlmCredentialRead[];
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

const scopeOptions: Array<{
  value: AgentScope;
  label: string;
  description: string;
}> = [
  {
    value: "organization",
    label: "Organization",
    description: "Available across this organization.",
  },
  {
    value: "workspace",
    label: "Workspace",
    description: "Available only inside one workspace.",
  },
];

function providerLabel(credential: LlmCredentialRead) {
  if (credential.provider === "openai_chatgpt" || credential.authMethod === "oauth") {
    return "OpenAI ChatGPT";
  }
  if (credential.provider === "openai") {
    return "OpenAI";
  }
  return credential.provider;
}

export function AgentForm({ agent, credentials, organization, workspaces }: AgentFormProps) {
  const router = useRouter();
  const isEditing = Boolean(agent);
  const [name, setName] = useState(agent?.name ?? "");
  const [description, setDescription] = useState(agent?.description ?? "");
  const [instructions, setInstructions] = useState(agent?.instructions ?? "");
  const [scope, setScope] = useState<AgentScope>(agent?.scope ?? "organization");
  const [workspaceId, setWorkspaceId] = useState(agent?.workspaceId ?? "");
  const [providerCredentialId, setProviderCredentialId] = useState(
    agent?.providerCredentialId ?? ""
  );
  const [modelName, setModelName] = useState(agent?.modelName ?? "");
  const [isActive, setIsActive] = useState(agent?.isActive ?? true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeWorkspaces = useMemo(
    () => workspaces.filter((workspace) => workspace.status === "active"),
    [workspaces]
  );

  const availableCredentials = useMemo(
    () =>
      credentials.filter((credential) => {
        if (!credential.isActive) {
          return false;
        }
        if (credential.visibility !== "workspace") {
          return true;
        }
        return scope === "workspace" && credential.workspaceId === workspaceId;
      }),
    [credentials, scope, workspaceId]
  );

  const canSave =
    name.trim().length > 0 &&
    instructions.trim().length > 0 &&
    !isSubmitting &&
    (scope !== "workspace" || workspaceId.length > 0);

  async function submitAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const payload: AgentPayload = {
      name: name.trim(),
      description: description.trim(),
      instructions: instructions.trim(),
      scope,
      workspaceId: scope === "workspace" ? workspaceId : null,
      providerCredentialId: providerCredentialId || null,
      modelName: modelName.trim(),
      ...(isEditing ? { isActive } : {}),
    };

    try {
      const response = await fetch(
        agent
          ? `/api/organizations/${organization.id}/agents/${agent.id}`
          : `/api/organizations/${organization.id}/agents`,
        {
          method: agent ? "PATCH" : "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      const data = (await response.json().catch(() => null)) as unknown;
      if (!response.ok) {
        throw new Error(errorMessage(data, "Agent could not be saved."));
      }
      router.push(`/org/${organization.id}/agents`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Agent could not be saved.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div>
              <CardTitle>{isEditing ? "Edit Agent" : "Create Agent"}</CardTitle>
              <CardDescription>
                Configure model access and operating instructions for an internal agent.
              </CardDescription>
            </div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
              <Bot className="size-5" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" onSubmit={submitAgent}>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="agent-name">Name</Label>
                <Input
                  id="agent-name"
                  maxLength={100}
                  onChange={(event) => setName(event.target.value)}
                  required
                  value={name}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="agent-model">Model</Label>
                <Input
                  id="agent-model"
                  maxLength={255}
                  onChange={(event) => setModelName(event.target.value)}
                  placeholder="gpt-4.1, claude-sonnet-4, local-model"
                  value={modelName}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="agent-description">Description</Label>
              <Input
                id="agent-description"
                maxLength={2000}
                onChange={(event) => setDescription(event.target.value)}
                value={description}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="agent-instructions">Instructions</Label>
              <textarea
                className="min-h-48 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                id="agent-instructions"
                maxLength={50000}
                onChange={(event) => setInstructions(event.target.value)}
                required
                value={instructions}
              />
            </div>

            <div className="space-y-3">
              <Label>Scope</Label>
              <div className="grid gap-3 md:grid-cols-2">
                {scopeOptions.map((option) => (
                  <label
                    className={cn(
                      "flex min-h-28 cursor-pointer flex-col justify-between rounded-lg border bg-white p-4 transition-colors",
                      scope === option.value
                        ? "border-primary ring-2 ring-primary/15"
                        : "border-[var(--outline-variant)] hover:border-primary/40"
                    )}
                    key={option.value}
                  >
                    <span>
                      <span className="flex items-center gap-2 text-sm font-semibold">
                        <input
                          checked={scope === option.value}
                          className="size-4 accent-primary"
                          name="scope"
                          onChange={() => setScope(option.value)}
                          type="radio"
                        />
                        {option.label}
                      </span>
                      <span className="mt-2 block text-sm leading-5 text-[var(--on-surface-variant)]">
                        {option.description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {scope === "workspace" ? (
              <div className="space-y-2">
                <Label htmlFor="agent-workspace">Workspace</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  id="agent-workspace"
                  onChange={(event) => {
                    setWorkspaceId(event.target.value);
                    setProviderCredentialId("");
                  }}
                  required
                  value={workspaceId}
                >
                  <option value="">Select workspace</option>
                  {activeWorkspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <div className="space-y-2">
              <Label htmlFor="agent-credential">LLM credential</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                id="agent-credential"
                onChange={(event) => setProviderCredentialId(event.target.value)}
                value={providerCredentialId}
              >
                <option value="">Use default routing</option>
                {availableCredentials.map((credential) => (
                  <option key={credential.id} value={credential.id}>
                    {credential.name} ({providerLabel(credential)})
                  </option>
                ))}
              </select>
            </div>

            {isEditing ? (
              <label className="flex min-h-10 items-center gap-3 rounded-md border border-[var(--outline-variant)] px-3 text-sm">
                <input
                  checked={isActive}
                  className="size-4 accent-primary"
                  onChange={(event) => setIsActive(event.target.checked)}
                  type="checkbox"
                />
                Active
              </label>
            ) : null}

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button asChild type="button" variant="outline">
                <Link href={`/org/${organization.id}/agents`}>Cancel</Link>
              </Button>
              <Button disabled={!canSave} type="submit">
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <Check />}
                {isEditing ? "Save changes" : "Create agent"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
