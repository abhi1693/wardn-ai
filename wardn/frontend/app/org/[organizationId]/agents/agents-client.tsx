"use client";

import { Bot, Loader2, MessageSquare, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
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

import type { LlmCredentialRead } from "../llm-credentials/types";
import { errorMessage } from "../tokens/token-form";

type AgentsClientProps = {
  agents: AgentRead[];
  credentials: LlmCredentialRead[];
  organization: OrganizationRead;
  workspaceId: string;
};

function credentialName(credentials: LlmCredentialRead[], credentialId?: string | null) {
  if (!credentialId) {
    return "Default routing";
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
  const [agents, setAgents] = useState(initialAgents);
  const [deletingAgentId, setDeletingAgentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const basePath = `/org/${organization.id}/workspace/${workspaceId}/agents`;
  const apiBasePath = `/api/organizations/${organization.id}/workspaces/${workspaceId}/agents`;

  async function deleteAgent(agent: AgentRead) {
    if (!window.confirm(`Delete ${agent.name}?`)) {
      return;
    }

    setDeletingAgentId(agent.id);
    setError(null);
    try {
      const response = await fetch(`${apiBasePath}/${agent.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(errorMessage(data, "Agent could not be deleted."));
      }
      setAgents((current) => current.filter((entry) => entry.id !== agent.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Agent could not be deleted.");
    } finally {
      setDeletingAgentId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents</CardTitle>
        <CardDescription>
          Internal agents configured to use organization LLM credentials.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        {agents.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Credential</TableHead>
                <TableHead>Tools</TableHead>
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
                  <TableCell>{agent.toolCount}</TableCell>
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
            <h3 className="text-base font-semibold">No agents</h3>
            <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
              Create an agent and assign an LLM credential to start validating the setup.
            </p>
            <Button asChild className="mt-4" size="sm">
              <Link href={`${basePath}/new`}>
                <Plus className="size-4" />
                New agent
              </Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
