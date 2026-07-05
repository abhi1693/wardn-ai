"use client";

import {
  CheckCircle2,
  CircleAlert,
  Loader2,
  Pencil,
  ShieldCheck,
  ShieldOff,
  Trash2,
} from "lucide-react";
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

type GuardrailMode = "allow" | "deny" | "require_confirmation";

const modeActions: Array<{
  icon: typeof CheckCircle2;
  label: string;
  mode: GuardrailMode;
}> = [
  { icon: CheckCircle2, label: "Allow", mode: "allow" },
  { icon: CircleAlert, label: "Require confirmation", mode: "require_confirmation" },
  { icon: ShieldOff, label: "Deny", mode: "deny" },
];

function modeLabel(mode: string) {
  if (mode === "require_confirmation") {
    return "Require confirmation";
  }
  return mode.slice(0, 1).toUpperCase() + mode.slice(1);
}

function modeActionClassName(mode: GuardrailMode, isActive: boolean) {
  if (mode === "allow") {
    return isActive
      ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
      : "text-emerald-700 hover:bg-emerald-50";
  }
  if (mode === "deny") {
    return isActive
      ? "bg-red-50 text-red-700 hover:bg-red-100"
      : "text-red-700 hover:bg-red-50";
  }
  return isActive
    ? "bg-amber-50 text-amber-700 hover:bg-amber-100"
    : "text-amber-700 hover:bg-amber-50";
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
  const [updatingMode, setUpdatingMode] = useState<{ mode: GuardrailMode; policyId: string } | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  async function updatePolicyMode(record: GuardrailPolicyRecord, mode: GuardrailMode) {
    if (record.policy.mode === mode || updatingMode) {
      return;
    }

    setUpdatingMode({ policyId: record.policy.id, mode });
    setError(null);
    try {
      const response = await fetch(policyEndpoint(organizationId, workspaceId, record.policy), {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(errorMessage(data, "Guardrail policy mode could not be changed."));
      }
      const updated = data as GuardrailPolicyRead;
      setPolicies((current) =>
        current.map((entry) =>
          entry.policy.id === updated.id ? { ...entry, policy: updated } : entry
        )
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Guardrail policy mode could not be changed."
      );
    } finally {
      setUpdatingMode(null);
    }
  }

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
                    <div
                      aria-label={`Policy mode: ${modeLabel(record.policy.mode)}`}
                      className="flex w-fit items-center gap-1 rounded-md border border-[var(--outline-variant)] bg-white p-1"
                    >
                      {modeActions.map((action) => {
                        const Icon = action.icon;
                        const isActive = record.policy.mode === action.mode;
                        const isUpdating =
                          updatingMode?.policyId === record.policy.id &&
                          updatingMode.mode === action.mode;
                        return (
                          <Button
                            aria-label={`${action.label} ${record.policy.name}`}
                            className={modeActionClassName(action.mode, isActive)}
                            disabled={Boolean(updatingMode)}
                            key={action.mode}
                            onClick={() => updatePolicyMode(record, action.mode)}
                            size="icon"
                            title={action.label}
                            type="button"
                            variant="ghost"
                          >
                            {isUpdating ? (
                              <Loader2 className="size-3.5 animate-spin" />
                            ) : (
                              <Icon className="size-3.5" />
                            )}
                          </Button>
                        );
                      })}
                    </div>
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
