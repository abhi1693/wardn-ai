"use client";

import { Loader2, Pencil, ShieldCheck, Trash2 } from "lucide-react";
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
import type { GuardrailPolicyRead } from "@/lib/api/generated/model";

import { errorMessage } from "../../../tokens/token-form";
import type {
  GuardrailAgentOption,
  GuardrailPolicyRecord,
  GuardrailServerOption,
  GuardrailToolOption,
} from "./data";

type GuardrailsClientProps = {
  agents: GuardrailAgentOption[];
  basePath: string;
  organizationId: string;
  policies: GuardrailPolicyRecord[];
  servers: GuardrailServerOption[];
  tools: GuardrailToolOption[];
  workspaceId: string;
};

function modeLabel(mode: string) {
  if (mode === "require_confirmation") {
    return "Require confirmation";
  }
  return mode.slice(0, 1).toUpperCase() + mode.slice(1);
}

function modeVariant(mode: string) {
  if (mode === "allow") {
    return "success" as const;
  }
  if (mode === "deny") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function policyEndpoint(organizationId: string, workspaceId: string, policy: GuardrailPolicyRead) {
  return `/api/organizations/${encodeURIComponent(
    organizationId
  )}/workspaces/${encodeURIComponent(
    workspaceId
  )}/guardrails/policies/${encodeURIComponent(policy.id)}`;
}

function targetLabel(
  policy: GuardrailPolicyRead,
  agents: GuardrailAgentOption[],
  servers: GuardrailServerOption[],
  tools: GuardrailToolOption[],
) {
  const parts = [];
  if (policy.agentId) {
    parts.push(
      agents.find((agent) => agent.id === policy.agentId)?.name ?? "Selected agent"
    );
  }
  if (policy.toolSchemaId) {
    parts.push(
      tools.find((tool) => tool.toolSchemaId === policy.toolSchemaId)?.label ??
        "Selected tool"
    );
  } else if (policy.installationId) {
    parts.push(
      servers.find((server) => server.installationId === policy.installationId)?.label ??
        "Selected MCP server"
    );
  }
  return parts.length > 0 ? parts.join(" / ") : "All agent tool calls";
}

export function GuardrailsClient({
  agents,
  basePath,
  organizationId,
  policies: initialPolicies,
  servers,
  tools,
  workspaceId,
}: GuardrailsClientProps) {
  const [policies, setPolicies] = useState(initialPolicies);
  const [deletingPolicyId, setDeletingPolicyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function deletePolicy(record: GuardrailPolicyRecord) {
    if (!window.confirm(`Delete ${record.policy.name}?`)) {
      return;
    }

    setDeletingPolicyId(record.policy.id);
    setError(null);
    try {
      const response = await fetch(policyEndpoint(organizationId, workspaceId, record.policy), {
        method: "DELETE",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(errorMessage(data, "Guardrail policy could not be deleted."));
      }
      setPolicies((current) =>
        current.filter((entry) => entry.policy.id !== record.policy.id)
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Guardrail policy could not be deleted."
      );
    } finally {
      setDeletingPolicyId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Guardrail Policies</CardTitle>
        <CardDescription>
          Control which MCP tool calls agents can run.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        {policies.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-28 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.map((record) => (
                <TableRow key={record.policy.id}>
                  <TableCell>
                    <div className="min-w-48">
                      <div className="font-medium">{record.policy.name}</div>
                      {record.policy.description ? (
                        <div className="mt-1 max-w-80 truncate text-xs text-[var(--on-surface-variant)]">
                          {record.policy.description}
                        </div>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={modeVariant(record.policy.mode)}>
                      {modeLabel(record.policy.mode)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <span className="block max-w-96 truncate text-sm">
                      {targetLabel(record.policy, agents, servers, tools)}
                    </span>
                  </TableCell>
                  <TableCell>{record.policy.priority}</TableCell>
                  <TableCell>
                    <Badge variant={record.policy.isActive ? "success" : "secondary"}>
                      {record.policy.isActive ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button
                        asChild
                        aria-label={`Edit ${record.policy.name}`}
                        size="icon"
                        variant="outline"
                      >
                        <Link href={`${basePath}/${record.policy.id}/edit`}>
                          <Pencil className="size-4" />
                        </Link>
                      </Button>
                      <Button
                        aria-label={`Delete ${record.policy.name}`}
                        disabled={deletingPolicyId === record.policy.id}
                        onClick={() => deletePolicy(record)}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        {deletingPolicyId === record.policy.id ? (
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
              <ShieldCheck className="size-5" />
            </div>
            <h3 className="text-base font-semibold">No guardrail policies</h3>
            <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
              Add a policy to allow, deny, or require confirmation for MCP tool calls.
            </p>
            <Button asChild className="mt-4" size="sm">
              <Link href={`${basePath}/new`}>New policy</Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
