"use client";

import { Bot, Loader2, MessageSquare, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AgentRead, OrganizationRead } from "@/lib/api/generated/model";
import {
  workspaceAgentsDelete,
  workspaceAgentsQuickStart,
} from "@/lib/api/generated/workspace-agents/workspace-agents";

import type { LlmCredentialRead } from "../llm-credentials/types";

type AgentsClientProps = {
  agents: AgentRead[];
  credentials: LlmCredentialRead[];
  organization: OrganizationRead;
  workspaceId: string;
};

function credentialName(credentials: LlmCredentialRead[], credentialId?: string | null) {
  if (!credentialId) {
    return "No credential";
  }
  const credential = credentials.find((entry) => entry.id === credentialId);
  if (!credential) {
    return credentialId;
  }
  const provider =
    credential.provider === "openai_chatgpt" || credential.authMethod === "oauth"
      ? "OpenAI ChatGPT"
      : credential.provider === "openai"
        ? "OpenAI"
        : credential.provider;
  return `${credential.name} (${provider})`;
}

export function AgentsClient({
  agents: initialAgents,
  credentials,
  organization,
  workspaceId,
}: AgentsClientProps) {
  const router = useRouter();
  const [agents, setAgents] = useState(initialAgents);
  const [deletingAgentId, setDeletingAgentId] = useState<string | null>(null);
  const [isStartingChat, setIsStartingChat] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const basePath = `/org/${organization.id}/workspace/${workspaceId}/agents`;
  const hasCredentials = credentials.length > 0;

  async function startChat() {
    if (!hasCredentials) {
      return;
    }
    setIsStartingChat(true);
    setError(null);
    try {
      const bundle = await workspaceAgentsQuickStart(organization.id, workspaceId);
      const agent = bundle.agent;
      setAgents((current) => {
        const existingIndex = current.findIndex((entry) => entry.id === agent.id);
        if (existingIndex === -1) {
          return [...current, agent];
        }
        return current.map((entry) => (entry.id === agent.id ? agent : entry));
      });
      router.push(
        `/org/${organization.id}/workspace/${workspaceId}/chat/${bundle.conversation.id}`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Workspace chat could not be started.");
    } finally {
      setIsStartingChat(false);
    }
  }

  async function deleteAgent(agent: AgentRead) {
    if (!window.confirm(`Delete ${agent.name}?`)) {
      return;
    }

    setDeletingAgentId(agent.id);
    setError(null);
    try {
      await workspaceAgentsDelete(organization.id, workspaceId, agent.id);
      setAgents((current) => current.filter((entry) => entry.id !== agent.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Agent could not be deleted.");
    } finally {
      setDeletingAgentId(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>Agents</CardTitle>
          <CardDescription>
            Chat with a workspace assistant or configure advanced agents.
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={isStartingChat || !hasCredentials}
            onClick={startChat}
            size="sm"
            title={hasCredentials ? undefined : "Add an LLM credential before starting chat"}
            type="button"
          >
            {isStartingChat ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <MessageSquare className="size-4" />
            )}
            Chat
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={`${basePath}/new`}>
              <Plus className="size-4" />
              Advanced
            </Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <AsyncFeedback variant="error">{error}</AsyncFeedback>
        ) : null}

        {agents.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Credential</TableHead>
                <TableHead>MCP</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-28 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.map((agent) => (
                <TableRow key={agent.id}>
                  <TableCell>
                    <div className="min-w-48">
                      <div className="font-medium">{agent.name}</div>
                      {agent.description ? (
                        <div className="mt-1 max-w-72 truncate text-xs text-[var(--on-surface-variant)]">
                          {agent.description}
                        </div>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>{agent.modelName || "Default"}</TableCell>
                  <TableCell>
                    <span className="block max-w-72 truncate">
                      {credentialName(credentials, agent.providerCredentialId)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">{agent.serverCount} servers</div>
                    <div className="text-xs text-[var(--on-surface-variant)]">
                      {agent.toolCount} tools
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={agent.isActive ? "success" : "secondary"}>
                      {agent.isActive ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button
                        asChild
                        aria-label={`Chat with ${agent.name}`}
                        size="icon"
                        variant="outline"
                      >
                        <Link href={`${basePath}/${agent.id}`}>
                          <MessageSquare className="size-4" />
                        </Link>
                      </Button>
                      <Button
                        asChild
                        aria-label={`Edit ${agent.name}`}
                        size="icon"
                        variant="outline"
                      >
                        <Link href={`${basePath}/${agent.id}/edit`}>
                          <Pencil className="size-4" />
                        </Link>
                      </Button>
                      <Button
                        aria-label={`Delete ${agent.name}`}
                        disabled={deletingAgentId === agent.id}
                        onClick={() => deleteAgent(agent)}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        {deletingAgentId === agent.id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <Trash2 className="size-4" />
                        )}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="rounded-lg border border-dashed border-[var(--outline-variant)] p-8 text-center">
            <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
              <Bot className="size-5" />
            </div>
            <h3 className="text-base font-semibold">
              {hasCredentials ? "No agents" : "No LLM credentials"}
            </h3>
            <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
              {hasCredentials
                ? "Start chatting now. Wardn will create a workspace assistant with an available LLM credential and workspace MCP servers."
                : "Add one LLM credential, then start workspace chat without configuring an agent first."}
            </p>
            {hasCredentials ? (
              <Button className="mt-4" disabled={isStartingChat} onClick={startChat} size="sm">
                {isStartingChat ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <MessageSquare className="size-4" />
                )}
                Chat
              </Button>
            ) : (
              <Button asChild className="mt-4" size="sm">
                <Link href={`/org/${organization.id}/llm-credentials/new`}>
                  <Plus className="size-4" />
                  Add credential
                </Link>
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
