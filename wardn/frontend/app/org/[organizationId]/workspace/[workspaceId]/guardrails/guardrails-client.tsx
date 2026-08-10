"use client";

import {
  CheckCircle2,
  CircleAlert,
  LockKeyhole,
  Loader2,
  Pencil,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UnlockKeyhole,
  WandSparkles,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/atoms/badge";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { Button } from "@/components/atoms/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import { Label } from "@/components/atoms/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import type {
  GuardrailPolicyRead,
  GuardrailPolicySimulationResponse,
  GuardrailSettingsRead,
} from "@/lib/api/generated/model";
import {
  workspaceGuardrailPoliciesDelete,
  workspaceGuardrailPoliciesUpdate,
} from "@/lib/api/generated/workspace-guardrail-policies/workspace-guardrail-policies";
import {
  workspaceGuardrailsCreateStarterPolicies,
  workspaceGuardrailsSimulatePolicy,
  workspaceGuardrailsUpdateSettings,
} from "@/lib/api/generated/workspace-guardrails/workspace-guardrails";

import type {
  GuardrailAgentOption,
  GuardrailPolicyRecord,
  GuardrailToolOption,
} from "./data";

type GuardrailsClientProps = {
  agents: GuardrailAgentOption[];
  basePath: string;
  initialSettings: GuardrailSettingsRead;
  organizationId: string;
  policies: GuardrailPolicyRecord[];
  tools: GuardrailToolOption[];
  workspaceId: string;
};

type GuardrailMode = "allow" | "deny" | "require_confirmation";
type RuleGroupOperator = "all" | "any";

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

function simulationStatusLabel(status: string) {
  if (status === "allowed") {
    return "Allowed";
  }
  if (status === "requires_confirmation") {
    return "Needs approval";
  }
  if (status === "installed_not_assigned") {
    return "Not assigned";
  }
  if (status === "tool_not_installed") {
    return "Not installed";
  }
  return "Blocked";
}

function simulationBadgeVariant(status: string) {
  if (status === "allowed") {
    return "success" as const;
  }
  if (status === "requires_confirmation") {
    return "outline" as const;
  }
  return "destructive" as const;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function ruleValueLabel(field: string, value: string, tools: GuardrailToolOption[]) {
  if (field === "tool_schema_id") {
    return tools.find((tool) => tool.toolSchemaId === value)?.label ?? "Selected tool";
  }
  if (field === "tool_name") {
    return value;
  }
  return value;
}

function ruleFieldLabel(field: string) {
  if (field === "tool_schema_id") {
    return "Tool";
  }
  if (field === "tool_name") {
    return "Tool name";
  }
  return "Rule";
}

function conditionsTargetLabel(
  conditions: unknown,
  tools: GuardrailToolOption[],
) {
  if (!isRecord(conditions) || !Array.isArray(conditions.rules)) {
    return "";
  }
  const operator: RuleGroupOperator = conditions.operator === "any" ? "any" : "all";
  const labels = conditions.rules
    .filter(isRecord)
    .flatMap((rule) => {
      if (typeof rule.field !== "string") {
        return [];
      }
      const field = rule.field;
      if (typeof rule.value === "string") {
        return [
          `${ruleFieldLabel(field)} is ${ruleValueLabel(field, rule.value, tools)}`,
        ];
      }
      if (Array.isArray(rule.value)) {
        const values = rule.value.filter((value): value is string => typeof value === "string");
        if (values.length === 0) {
          return [];
        }
        return [
          `${ruleFieldLabel(field)} is one of ${values
            .map((value) => ruleValueLabel(field, value, tools))
            .join(", ")}`,
        ];
      }
      return [];
    });
  if (labels.length === 0) {
    return "";
  }
  return `${operator === "any" ? "Any" : "All"}: ${labels.join(
    operator === "any" ? " OR " : " AND "
  )}`;
}

function targetLabel(policy: GuardrailPolicyRead, tools: GuardrailToolOption[]) {
  const conditionLabel = conditionsTargetLabel(policy.conditions, tools);
  if (conditionLabel) {
    return conditionLabel;
  }
  return "All tool calls";
}

function sortPolicyRecords(records: GuardrailPolicyRecord[]) {
  return [...records].sort((left, right) => {
    const priorityCompare = left.policy.priority - right.policy.priority;
    if (priorityCompare !== 0) {
      return priorityCompare;
    }
    return left.policy.name.localeCompare(right.policy.name);
  });
}

export function GuardrailsClient({
  agents,
  basePath,
  initialSettings,
  organizationId,
  policies: initialPolicies,
  tools,
  workspaceId,
}: GuardrailsClientProps) {
  const [policies, setPolicies] = useState(sortPolicyRecords(initialPolicies));
  const [settings, setSettings] = useState(initialSettings);
  const [deletingPolicyId, setDeletingPolicyId] = useState<string | null>(null);
  const [generatingStarterPolicies, setGeneratingStarterPolicies] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState(agents[0]?.agentId ?? "");
  const [selectedToolSchemaId, setSelectedToolSchemaId] = useState(tools[0]?.toolSchemaId ?? "");
  const [simulationArguments, setSimulationArguments] = useState("{}");
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [simulationResult, setSimulationResult] =
    useState<GuardrailPolicySimulationResponse | null>(null);
  const [simulatingPolicy, setSimulatingPolicy] = useState(false);
  const [updatingMode, setUpdatingMode] = useState<{ mode: GuardrailMode; policyId: string } | null>(
    null
  );
  const [updatingSettings, setUpdatingSettings] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const activePolicies = policies.filter((record) => record.policy.isActive);
  const summaryCards = [
    {
      count: activePolicies.filter((record) => record.policy.mode === "allow").length,
      detail: "Explicitly permitted tool calls.",
      icon: CheckCircle2,
      label: "Connected",
    },
    {
      count: activePolicies.filter((record) => record.policy.mode === "deny").length,
      detail: "Tool calls that will be blocked.",
      icon: ShieldOff,
      label: "Blocked by policy",
    },
    {
      count: activePolicies.filter((record) => record.policy.mode === "require_confirmation").length,
      detail: "Tool calls that need approval.",
      icon: CircleAlert,
      label: "Needs approval",
    },
    {
      count: policies.filter((record) => !record.policy.isActive).length,
      detail: "Saved rules that are not active.",
      icon: ShieldCheck,
      label: "Inactive",
    },
  ];

  async function updatePolicyMode(record: GuardrailPolicyRecord, mode: GuardrailMode) {
    if (record.policy.mode === mode || updatingMode) {
      return;
    }

    setUpdatingMode({ policyId: record.policy.id, mode });
    setError(null);
    setNotice(null);
    try {
      const updated = await workspaceGuardrailPoliciesUpdate(
        organizationId,
        workspaceId,
        record.policy.id,
        { mode }
      );
      setPolicies((current) =>
        current.map((entry) =>
          entry.policy.id === updated.id ? { ...entry, policy: updated } : entry
        )
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Access rule mode could not be changed."
      );
    } finally {
      setUpdatingMode(null);
    }
  }

  async function deletePolicy(record: GuardrailPolicyRecord) {
    setDeletingPolicyId(record.policy.id);
    setError(null);
    setNotice(null);
    try {
      await workspaceGuardrailPoliciesDelete(organizationId, workspaceId, record.policy.id);
      setPolicies((current) =>
        current.filter((entry) => entry.policy.id !== record.policy.id)
      );
    } finally {
      setDeletingPolicyId(null);
    }
  }

  async function simulatePolicy() {
    if (!selectedAgentId || !selectedToolSchemaId || simulatingPolicy) {
      return;
    }

    let parsedArguments: unknown = {};
    const trimmedArguments = simulationArguments.trim();
    if (trimmedArguments) {
      try {
        parsedArguments = JSON.parse(trimmedArguments);
      } catch {
        setSimulationError("Arguments must be valid JSON.");
        setSimulationResult(null);
        return;
      }
    }
    if (
      typeof parsedArguments !== "object" ||
      parsedArguments === null ||
      Array.isArray(parsedArguments)
    ) {
      setSimulationError("Arguments must be a JSON object.");
      setSimulationResult(null);
      return;
    }

    setSimulatingPolicy(true);
    setSimulationError(null);
    setSimulationResult(null);
    try {
      const response = await workspaceGuardrailsSimulatePolicy(
        organizationId,
        workspaceId,
        {
          agentId: selectedAgentId,
          arguments: parsedArguments as Record<string, unknown>,
          toolSchemaId: selectedToolSchemaId,
        }
      );
      setSimulationResult(response);
    } catch (caught) {
      setSimulationError(
        caught instanceof Error
          ? caught.message
          : "Access rule simulation could not be completed."
      );
    } finally {
      setSimulatingPolicy(false);
    }
  }

  async function updateDefaultDeny(defaultDeny: boolean) {
    if (settings.defaultDeny === defaultDeny || updatingSettings) {
      return;
    }

    setUpdatingSettings(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await workspaceGuardrailsUpdateSettings(organizationId, workspaceId, {
        defaultDeny,
      });
      setSettings(updated);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Workspace access mode could not be changed."
      );
    } finally {
      setUpdatingSettings(false);
    }
  }

  async function createStarterPolicies() {
    if (generatingStarterPolicies) {
      return;
    }

    setGeneratingStarterPolicies(true);
    setError(null);
    setNotice(null);
    try {
      const response = await workspaceGuardrailsCreateStarterPolicies(
        organizationId,
        workspaceId,
        { enableDefaultDeny: true }
      );
      setSettings({
        workspaceId: response.workspaceId,
        defaultDeny: response.defaultDeny,
      });
      setPolicies((current) =>
        sortPolicyRecords([
          ...current,
          ...(response.createdPolicies ?? []).map((policy) => ({ policy })),
        ])
      );
      const createdCount = response.createdPolicies?.length ?? 0;
      setNotice(
        createdCount > 0
          ? `Created ${createdCount} starter access rules.`
          : "No starter access rules were needed."
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Starter access rules could not be generated."
      );
    } finally {
      setGeneratingStarterPolicies(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Access Rules</CardTitle>
        <CardDescription>
          Control which workspace tool calls agents can run, block, or pause for approval.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <AsyncFeedback variant="error">{error}</AsyncFeedback>
        ) : null}
        {notice ? (
          <AsyncFeedback variant="success">{notice}</AsyncFeedback>
        ) : null}

        <section className="rounded-md border border-[var(--outline-variant)] bg-[var(--surface-container-lowest)] p-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-[var(--surface-container)] text-primary">
                {settings.defaultDeny ? (
                  <LockKeyhole className="size-5" />
                ) : (
                  <UnlockKeyhole className="size-5" />
                )}
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold">Workspace access mode</h3>
                  <Badge variant={settings.defaultDeny ? "success" : "secondary"}>
                    {settings.defaultDeny ? "Default deny" : "Open by default"}
                  </Badge>
                </div>
                <p className="mt-1 max-w-3xl text-sm text-[var(--on-surface-variant)]">
                  {settings.defaultDeny
                    ? "Tool calls must match an active allow rule, deny rule, or approval rule."
                    : "Unmatched tool calls are allowed unless an active allow rule exists."}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={updatingSettings || generatingStarterPolicies}
                onClick={() => updateDefaultDeny(!settings.defaultDeny)}
                size="sm"
                type="button"
                variant="outline"
              >
                {updatingSettings ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : settings.defaultDeny ? (
                  <UnlockKeyhole className="size-4" />
                ) : (
                  <LockKeyhole className="size-4" />
                )}
                {settings.defaultDeny ? "Disable default deny" : "Enable default deny"}
              </Button>
              <Button
                disabled={updatingSettings || generatingStarterPolicies}
                onClick={createStarterPolicies}
                size="sm"
                type="button"
              >
                {generatingStarterPolicies ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <WandSparkles className="size-4" />
                )}
                Generate starter rules
              </Button>
            </div>
          </div>
        </section>

        <section className="rounded-md border border-[var(--outline-variant)] bg-[var(--surface-container-lowest)] p-4">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-semibold">Policy simulator</h3>
              <p className="text-sm text-[var(--on-surface-variant)]">
                Check whether an agent can run a selected tool before it executes.
              </p>
            </div>
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
              <div className="space-y-1.5">
                <Label htmlFor="guardrail-simulator-agent">Agent</Label>
                <Select
                  disabled={agents.length === 0 || simulatingPolicy}
                  onValueChange={setSelectedAgentId}
                  value={selectedAgentId}
                >
                  <SelectTrigger id="guardrail-simulator-agent">
                    <SelectValue placeholder="Select agent" />
                  </SelectTrigger>
                  <SelectContent>
                    {agents.map((agent) => (
                      <SelectItem key={agent.agentId} value={agent.agentId}>
                        {agent.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="guardrail-simulator-tool">Tool</Label>
                <Select
                  disabled={tools.length === 0 || simulatingPolicy}
                  onValueChange={setSelectedToolSchemaId}
                  value={selectedToolSchemaId}
                >
                  <SelectTrigger id="guardrail-simulator-tool">
                    <SelectValue placeholder="Select tool" />
                  </SelectTrigger>
                  <SelectContent>
                    {tools.map((tool) => (
                      <SelectItem key={tool.toolSchemaId} value={tool.toolSchemaId}>
                        {tool.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="guardrail-simulator-arguments">Arguments</Label>
              <textarea
                className="min-h-24 w-full resize-y rounded-[var(--radius)] border border-input bg-card px-3 py-2 font-mono text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/15 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60"
                disabled={simulatingPolicy}
                id="guardrail-simulator-arguments"
                onChange={(event) => setSimulationArguments(event.target.value)}
                spellCheck={false}
                value={simulationArguments}
              />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                disabled={!selectedAgentId || !selectedToolSchemaId || simulatingPolicy}
                onClick={simulatePolicy}
                size="sm"
                type="button"
              >
                {simulatingPolicy ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ShieldCheck className="size-4" />
                )}
                Simulate
              </Button>
              {simulationError ? (
                <span className="text-sm text-red-700">{simulationError}</span>
              ) : null}
            </div>
            {simulationResult ? (
              <div className="rounded-md border border-border bg-card p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={simulationBadgeVariant(simulationResult.status)}>
                    {simulationStatusLabel(simulationResult.status)}
                  </Badge>
                  <span className="text-sm font-medium">
                    {simulationResult.toolName || "Selected tool"}
                  </span>
                  {simulationResult.configName ? (
                    <span className="text-sm text-[var(--on-surface-variant)]">
                      on {simulationResult.configName}
                    </span>
                  ) : null}
                </div>
                <p className="mt-2 text-sm text-[var(--on-surface-variant)]">
                  {simulationResult.reason}
                </p>
                <div className="mt-3 grid gap-2 text-xs text-[var(--on-surface-variant)] sm:grid-cols-4">
                  <div>
                    <span className="font-medium text-foreground">Installed:</span>{" "}
                    {simulationResult.installed ? "Yes" : "No"}
                  </div>
                  <div>
                    <span className="font-medium text-foreground">Assigned:</span>{" "}
                    {simulationResult.assigned ? "Yes" : "No"}
                  </div>
                  <div>
                    <span className="font-medium text-foreground">Policy:</span>{" "}
                    {simulationResult.decision.policyName || "No matching rule"}
                  </div>
                  <div>
                    <span className="font-medium text-foreground">Matched:</span>{" "}
                    {simulationResult.decision.matchedPolicyIds?.length ?? 0}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <section className="grid gap-3 md:grid-cols-4">
          {summaryCards.map((card) => {
            const Icon = card.icon;
            return (
              <div
                className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]"
                key={card.label}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">{card.label}</div>
                    <div className="mt-1 text-xs leading-4 text-muted-foreground">
                      {card.detail}
                    </div>
                  </div>
                  <Icon className="size-4 text-muted-foreground" />
                </div>
                <div className="mt-3 text-2xl font-semibold">{card.count}</div>
              </div>
            );
          })}
        </section>

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
                      className="flex w-fit items-center gap-1 rounded-md border border-[var(--outline-variant)] bg-card p-1"
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
                      {targetLabel(record.policy, tools)}
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
                      <ConfirmActionDialog
                        actionLabel="Delete rule"
                        description="This rule will stop protecting matching tool calls immediately."
                        onConfirm={() => deletePolicy(record)}
                        title={`Delete ${record.policy.name}?`}
                        variant="destructive"
                      >
                        <Button
                          aria-label={`Delete ${record.policy.name}`}
                          disabled={deletingPolicyId === record.policy.id}
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
                      </ConfirmActionDialog>
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
            <h3 className="text-base font-semibold">No access rules</h3>
            <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
              Add an access rule to allow, deny, or require confirmation for tool calls.
            </p>
            <Button asChild className="mt-4" size="sm">
              <Link href={`${basePath}/new`}>New rule</Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
