"use client";

import { Bot, Check, Loader2, Server } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";

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
import type { AgentRead, OrganizationRead } from "@/lib/api/generated/model";

import type { LlmCredentialRead } from "../llm-credentials/types";
import { errorMessage } from "../tokens/token-form";
import {
  ALL_SERVER_TOOLS,
  type AgentAvailableServer,
  type AgentAvailableTool,
  type AgentServerToolAssignment,
} from "./tool-types";

type AgentPayload = {
  name: string;
  description: string;
  instructions: string;
  scope: "workspace";
  workspaceId: string;
  providerCredentialId?: string | null;
  modelName: string;
  isActive?: boolean;
};

type AgentFormProps = {
  agent?: AgentRead;
  assignedServerAssignments?: AgentServerToolAssignment[];
  availableServers?: AgentAvailableServer[];
  availableTools?: AgentAvailableTool[];
  credentials: LlmCredentialRead[];
  organization: OrganizationRead;
  fixedWorkspaceId: string;
};

type ProviderModel = {
  id: string;
  name: string;
};

type AvailableToolGroup = {
  configName: string;
  installationId: string;
  serverName: string;
  tools: AgentAvailableTool[];
};

type ServerBindingMode = "none" | "server" | "tools";

function providerLabel(credential: LlmCredentialRead) {
  if (credential.provider === "openai_chatgpt" || credential.authMethod === "oauth") {
    return "OpenAI ChatGPT";
  }
  if (credential.provider === "openai") {
    return "OpenAI";
  }
  return credential.provider;
}

export function AgentForm({
  agent,
  assignedServerAssignments = [],
  availableServers = [],
  availableTools = [],
  credentials,
  fixedWorkspaceId,
  organization,
}: AgentFormProps) {
  const router = useRouter();
  const isEditing = Boolean(agent);
  const availableCredentials = useMemo(
    () =>
      credentials.filter((credential) => {
        if (!credential.isActive) {
          return false;
        }
        if (credential.visibility !== "workspace") {
          return true;
        }
        return credential.workspaceId === fixedWorkspaceId;
      }),
    [credentials, fixedWorkspaceId]
  );
  const initialProviderCredentialId =
    agent?.providerCredentialId &&
    availableCredentials.some((credential) => credential.id === agent.providerCredentialId)
      ? agent.providerCredentialId
      : availableCredentials[0]?.id ?? "";
  const [name, setName] = useState(agent?.name ?? "");
  const [description, setDescription] = useState(agent?.description ?? "");
  const [instructions, setInstructions] = useState(agent?.instructions ?? "");
  const [providerCredentialId, setProviderCredentialId] = useState(initialProviderCredentialId);
  const [modelName, setModelName] = useState(
    initialProviderCredentialId === agent?.providerCredentialId ? agent?.modelName ?? "" : ""
  );
  const [isActive, setIsActive] = useState(agent?.isActive ?? true);
  const [selectedServerTools, setSelectedServerTools] = useState<Record<string, string[]>>(
    Object.fromEntries(
      assignedServerAssignments.map((assignment) => [
        assignment.installationId,
        assignment.toolSchemaIds,
      ])
    )
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [modelOptions, setModelOptions] = useState<ProviderModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(Boolean(initialProviderCredentialId));
  const [modelError, setModelError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const effectiveProviderCredentialId =
    providerCredentialId &&
    availableCredentials.some((credential) => credential.id === providerCredentialId)
      ? providerCredentialId
      : "";

  useEffect(() => {
    if (!effectiveProviderCredentialId) {
      return;
    }

    const abortController = new AbortController();

    async function loadModels() {
      try {
        const response = await fetch(
          `/api/organizations/${organization.id}/llm/provider-credentials/${effectiveProviderCredentialId}/models`,
          { signal: abortController.signal }
        );
        const data = (await response.json().catch(() => null)) as
          | { models?: ProviderModel[] }
          | unknown;
        if (!response.ok) {
          throw new Error(errorMessage(data, "Models could not be loaded."));
        }
        setModelOptions(
          Array.isArray((data as { models?: unknown }).models)
            ? ((data as { models: ProviderModel[] }).models ?? [])
            : []
        );
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setModelOptions([]);
        setModelError(caught instanceof Error ? caught.message : "Models could not be loaded.");
      } finally {
        if (!abortController.signal.aborted) {
          setIsLoadingModels(false);
        }
      }
    }

    void loadModels();
    return () => abortController.abort();
  }, [organization.id, effectiveProviderCredentialId]);

  const selectedModelUnavailable =
    Boolean(modelName) &&
    modelOptions.length > 0 &&
    !modelOptions.some((model) => model.id === modelName);

  const canSave =
    name.trim().length > 0 &&
    instructions.trim().length > 0 &&
    !isSubmitting &&
    !isLoadingModels &&
    !modelError &&
    !selectedModelUnavailable &&
    Boolean(effectiveProviderCredentialId) &&
    modelName.trim().length > 0;

  const formBasePath = `/api/organizations/${organization.id}/workspaces/${fixedWorkspaceId}/agents`;
  const pageBasePath = `/org/${organization.id}/workspace/${fixedWorkspaceId}/agents`;

  const availableToolGroups = useMemo(() => {
    const groups = new Map<string, AvailableToolGroup>();
    for (const server of availableServers) {
      groups.set(server.installationId, {
        configName: server.configName,
        installationId: server.installationId,
        serverName: server.serverName,
        tools: [],
      });
    }
    for (const tool of availableTools) {
      const group = groups.get(tool.installationId);
      if (group) {
        group.tools.push(tool);
      } else {
        groups.set(tool.installationId, {
          configName: tool.configName,
          installationId: tool.installationId,
          serverName: tool.serverName,
          tools: [tool],
        });
      }
    }
    return Array.from(groups.values()).sort((left, right) =>
      `${left.serverName}/${left.configName}`.localeCompare(
        `${right.serverName}/${right.configName}`
      )
    );
  }, [availableServers, availableTools]);

  const selectedServerCount = availableToolGroups.filter(
    (group) => (selectedServerTools[group.installationId] ?? []).length > 0
  ).length;
  const exposedToolCount = availableToolGroups.reduce((total, group) => {
    const selected = selectedServerTools[group.installationId] ?? [];
    if (selected.includes(ALL_SERVER_TOOLS)) {
      return total + group.tools.length;
    }
    return total + selected.length;
  }, 0);

  function selectedToolsForServer(installationId: string) {
    return selectedServerTools[installationId] ?? [];
  }

  function serverBindingMode(installationId: string): ServerBindingMode {
    const selected = selectedToolsForServer(installationId);
    if (selected.includes(ALL_SERVER_TOOLS)) {
      return "server";
    }
    return selected.length > 0 ? "tools" : "none";
  }

  function setServerSelection(installationId: string, toolSchemaIds: string[]) {
    setSelectedServerTools((current) => {
      const next = { ...current };
      if (toolSchemaIds.length > 0) {
        next[installationId] = toolSchemaIds;
      } else {
        delete next[installationId];
      }
      return next;
    });
  }

  function setServerBindingMode(group: AvailableToolGroup, mode: ServerBindingMode) {
    if (mode === "server") {
      setServerSelection(group.installationId, [ALL_SERVER_TOOLS]);
      return;
    }
    if (mode === "tools") {
      const selected = selectedToolsForServer(group.installationId).filter(
        (entry) => entry !== ALL_SERVER_TOOLS
      );
      if (group.tools.length === 0) {
        setServerSelection(group.installationId, [ALL_SERVER_TOOLS]);
        return;
      }
      setServerSelection(
        group.installationId,
        selected.length > 0 ? selected : group.tools.map((tool) => tool.toolSchemaId)
      );
      return;
    }
    setServerSelection(group.installationId, []);
  }

  function toggleTool(installationId: string, toolSchemaId: string) {
    const selected = selectedToolsForServer(installationId);
    if (selected.includes(ALL_SERVER_TOOLS)) {
      return;
    }
    setServerSelection(
      installationId,
      selected.includes(toolSchemaId)
        ? selected.filter((entry) => entry !== toolSchemaId)
        : [...selected, toolSchemaId]
    );
  }

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
      scope: "workspace",
      workspaceId: fixedWorkspaceId,
      providerCredentialId: effectiveProviderCredentialId,
      modelName: modelName.trim(),
      ...(isEditing ? { isActive } : {}),
    };

    try {
      const response = await fetch(
        agent ? `${formBasePath}/${agent.id}` : formBasePath,
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
      const savedAgentId = (data as { id?: string } | null)?.id ?? agent?.id;
      if (savedAgentId) {
        const servers = Object.entries(selectedServerTools).map(
          ([installationId, toolSchemaIds]) => ({
            installationId,
            toolSchemaIds,
          })
        );
        const toolsResponse = await fetch(`${formBasePath}/${savedAgentId}/tools`, {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ servers }),
        });
        const toolsData = (await toolsResponse.json().catch(() => null)) as unknown;
        if (!toolsResponse.ok) {
          throw new Error(errorMessage(toolsData, "Agent tools could not be saved."));
        }
      }
      router.push(pageBasePath);
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

            <div className="space-y-2">
              <Label htmlFor="agent-credential">LLM credential</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-70"
                disabled={availableCredentials.length === 0}
                id="agent-credential"
                onChange={(event) => {
                  const nextCredentialId = event.target.value;
                  setProviderCredentialId(nextCredentialId);
                  setModelName("");
                  setModelOptions([]);
                  setModelError(null);
                  setIsLoadingModels(Boolean(nextCredentialId));
                }}
                value={providerCredentialId}
              >
                {availableCredentials.length === 0 ? (
                  <option value="">No LLM credentials available</option>
                ) : null}
                {availableCredentials.map((credential) => (
                  <option key={credential.id} value={credential.id}>
                    {credential.name} ({providerLabel(credential)})
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="agent-model">Model</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-70"
                disabled={
                  !effectiveProviderCredentialId || isLoadingModels || Boolean(modelError)
                }
                id="agent-model"
                onChange={(event) => setModelName(event.target.value)}
                required={Boolean(effectiveProviderCredentialId)}
                value={modelName}
              >
                <option value="">
                  {effectiveProviderCredentialId
                    ? isLoadingModels
                      ? "Loading models"
                      : "Select model"
                    : "Select an LLM credential first"}
                </option>
                {selectedModelUnavailable ? (
                  <option value={modelName}>{modelName} (unavailable)</option>
                ) : null}
                {modelOptions.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
              {modelError ? (
                <div className="text-sm text-red-700">{modelError}</div>
              ) : null}
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

            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <Label>MCP servers</Label>
                <span className="text-xs text-[var(--on-surface-variant)]">
                  {selectedServerCount} bound / {exposedToolCount} tools
                </span>
              </div>
              {availableToolGroups.length > 0 ? (
                <div className="max-h-96 space-y-3 overflow-y-auto rounded-md border border-[var(--outline-variant)] p-2">
                  {availableToolGroups.map((group) => {
                    const selected = selectedToolsForServer(group.installationId);
                    const mode = serverBindingMode(group.installationId);
                    return (
                      <div
                        className="rounded-md border border-[var(--outline-variant)] bg-white"
                        key={group.installationId}
                      >
                        <div className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="flex min-w-0 items-start gap-3">
                            <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[var(--surface-container)] text-primary">
                              <Server className="size-4" />
                            </div>
                            <div className="min-w-0">
                              <div className="truncate text-sm font-medium">
                                {group.configName}
                              </div>
                              <div className="mt-1 truncate text-xs text-[var(--on-surface-variant)]">
                                {group.serverName}
                              </div>
                            </div>
                          </div>
                          <fieldset className="grid gap-2 text-sm sm:grid-cols-3">
                            <label className="flex cursor-pointer items-center gap-2 rounded-md border border-[var(--outline-variant)] px-3 py-2">
                              <input
                                checked={mode === "none"}
                                className="size-4 accent-primary"
                                name={`server-binding-${group.installationId}`}
                                onChange={() => setServerBindingMode(group, "none")}
                                type="radio"
                              />
                              Not bound
                            </label>
                            <label className="flex cursor-pointer items-center gap-2 rounded-md border border-[var(--outline-variant)] px-3 py-2">
                              <input
                                checked={mode === "server"}
                                className="size-4 accent-primary"
                                name={`server-binding-${group.installationId}`}
                                onChange={() => setServerBindingMode(group, "server")}
                                type="radio"
                              />
                              Entire server
                            </label>
                            <label className="flex cursor-pointer items-center gap-2 rounded-md border border-[var(--outline-variant)] px-3 py-2">
                              <input
                                checked={mode === "tools"}
                                className="size-4 accent-primary"
                                disabled={group.tools.length === 0}
                                name={`server-binding-${group.installationId}`}
                                onChange={() => setServerBindingMode(group, "tools")}
                                type="radio"
                              />
                              Selected tools
                            </label>
                          </fieldset>
                        </div>
                        {mode === "tools" ? (
                          <div className="border-t border-[var(--outline-variant)] py-1">
                          {group.tools.map((tool) => (
                            <label
                              className="flex cursor-pointer items-start gap-3 px-4 py-2 text-sm hover:bg-[var(--surface-container)]"
                              key={tool.toolSchemaId}
                            >
                              <input
                                checked={selected.includes(tool.toolSchemaId)}
                                className="mt-1 size-4 accent-primary"
                                onChange={() =>
                                  toggleTool(group.installationId, tool.toolSchemaId)
                                }
                                type="checkbox"
                              />
                              <span className="min-w-0 flex-1">
                                <span className="block font-medium">
                                  {tool.title || tool.toolName}
                                </span>
                                <span className="mt-1 block truncate text-xs text-[var(--on-surface-variant)]">
                                  {tool.toolName}
                                </span>
                                {tool.description ? (
                                  <span className="mt-1 block text-xs leading-5 text-[var(--on-surface-variant)]">
                                    {tool.description}
                                  </span>
                                ) : null}
                              </span>
                            </label>
                          ))}
                        </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-[var(--outline-variant)] px-3 py-6 text-sm text-[var(--on-surface-variant)]">
                  No MCP servers are available in this workspace yet.
                </div>
              )}
            </div>

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button asChild type="button" variant="outline">
                <Link href={pageBasePath}>Cancel</Link>
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
