"use client";

import { CheckCircle2, CircleAlert, Loader2, ShieldOff } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import type { MCPGatewayToolApprovalRead } from "@/lib/api/generated/model";
import { workspaceMcpGatewayDecideToolApproval } from "@/lib/api/generated/workspace-mcp-gateway/workspace-mcp-gateway";
import { formatUserDateTime } from "@/lib/date-time";
import { cn } from "@/lib/utils";

type ConnectionApprovalsClientProps = {
  initialApprovals: MCPGatewayToolApprovalRead[];
  loadError?: string;
  organizationId: string;
  workspaceId: string;
};

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function formatDate(value: string) {
  return formatUserDateTime(value, "Unknown", undefined, "en");
}

function jsonPreview(value: unknown) {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function approvalVariant(status: string) {
  if (status === "completed") {
    return "success" as const;
  }
  if (status === "failed" || status === "denied") {
    return "destructive" as const;
  }
  return "secondary" as const;
}

export function ConnectionApprovalsClient({
  initialApprovals,
  loadError = "",
  organizationId,
  workspaceId,
}: ConnectionApprovalsClientProps) {
  const searchParams = useSearchParams();
  const highlightedApprovalId = searchParams.get("approvalId") ?? "";
  const [approvals, setApprovals] = useState(initialApprovals);
  const [decisions, setDecisions] = useState<Record<string, string>>({});

  async function decideApproval(approvalId: string, decision: "approve" | "deny") {
    if (decisions[approvalId]) {
      return;
    }
    setDecisions((current) => ({ ...current, [approvalId]: decision }));
    try {
      const result = await workspaceMcpGatewayDecideToolApproval(
        organizationId,
        workspaceId,
        approvalId,
        { decision }
      );
      setApprovals((current) =>
        current.map((approval) =>
          approval.id === approvalId
            ? {
                ...approval,
                error: result.error ?? "",
                result: result.result ?? undefined,
                status: result.status,
                updatedAt: new Date().toISOString(),
              }
            : approval
        )
      );
    } catch (caught) {
      setApprovals((current) =>
        current.map((approval) =>
          approval.id === approvalId
            ? {
                ...approval,
                error: caught instanceof Error ? caught.message : "Approval failed.",
                status: "failed",
                updatedAt: new Date().toISOString(),
              }
            : approval
        )
      );
    } finally {
      setDecisions((current) => {
        const next = { ...current };
        delete next[approvalId];
        return next;
      });
    }
  }

  const visibleApprovals = approvals.filter((approval) => approval.status !== "denied");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pending Approvals</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {loadError ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {loadError}
          </div>
        ) : null}
        {visibleApprovals.length > 0 ? (
          visibleApprovals.map((approval) => {
            const policyName = stringValue(approval.guardrail.policyName);
            const policyMessage = stringValue(approval.guardrail.message);
            const decision = decisions[approval.id] ?? "";
            const isPending = approval.status === "pending";
            return (
              <div
                className={cn(
                  "rounded-md border border-border px-3 py-3",
                  highlightedApprovalId === approval.id && "border-amber-400 bg-amber-50"
                )}
                key={approval.id}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      <CircleAlert className="size-4 shrink-0 text-amber-600" />
                      <div className="min-w-0 truncate font-medium">{approval.toolName}</div>
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      {policyName || policyMessage || "Workspace guardrail"}
                    </div>
                    <div className="mt-1 font-mono text-xs text-muted-foreground">
                      {formatDate(approval.createdAt)}
                    </div>
                  </div>
                  <Badge variant={approvalVariant(approval.status)}>{approval.status}</Badge>
                </div>

                {policyMessage ? (
                  <div className="mt-3 rounded border border-border bg-muted px-2 py-2 text-xs leading-5 text-muted-foreground">
                    {policyMessage}
                  </div>
                ) : null}

                <details className="mt-3 rounded border border-border bg-background">
                  <summary className="cursor-pointer px-2 py-1.5 text-xs font-medium text-muted-foreground">
                    Arguments
                  </summary>
                  <pre className="max-h-52 overflow-auto border-t border-border px-2 py-2 font-mono text-[11px] leading-5 whitespace-pre-wrap">
                    {jsonPreview(approval.arguments)}
                  </pre>
                </details>

                {approval.result ? (
                  <details className="mt-3 rounded border border-border bg-background">
                    <summary className="cursor-pointer px-2 py-1.5 text-xs font-medium text-muted-foreground">
                      Result
                    </summary>
                    <pre className="max-h-52 overflow-auto border-t border-border px-2 py-2 font-mono text-[11px] leading-5 whitespace-pre-wrap">
                      {jsonPreview(approval.result)}
                    </pre>
                  </details>
                ) : null}

                {approval.error ? (
                  <div className="mt-3 rounded border border-red-200 bg-red-50 px-2 py-2 text-xs text-red-700">
                    {approval.error}
                  </div>
                ) : null}

                {isPending ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      className="h-8 px-2.5 text-xs"
                      disabled={Boolean(decision)}
                      onClick={() => decideApproval(approval.id, "approve")}
                      size="sm"
                      type="button"
                    >
                      {decision === "approve" ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <CheckCircle2 className="size-3.5" />
                      )}
                      Approve
                    </Button>
                    <Button
                      className="h-8 px-2.5 text-xs"
                      disabled={Boolean(decision)}
                      onClick={() => decideApproval(approval.id, "deny")}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      {decision === "deny" ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <ShieldOff className="size-3.5" />
                      )}
                      Deny
                    </Button>
                  </div>
                ) : null}
              </div>
            );
          })
        ) : (
          <div className="rounded-md border border-dashed border-border px-3 py-6 text-center">
            <div className="font-medium">No pending approvals</div>
            <div className="mx-auto mt-1 max-w-sm text-sm leading-6 text-muted-foreground">
              Gateway calls that pause at a guardrail appear here.
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
