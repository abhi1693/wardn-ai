"use client";

import { RefreshCw, RotateCcw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  workspaceAgentRunsCancel,
  workspaceAgentRunsRerun,
} from "@/lib/api/generated/workspace-agent-runs/workspace-agent-runs";

const rerunTimeoutMs = 10 * 60_000;

type AgentRunActionsProps = {
  canCancel?: boolean;
  canRerun?: boolean;
  organizationId: string;
  runId: string;
  variant?: "icon" | "label";
  workspaceId: string;
};

function runHref(organizationId: string, workspaceId: string, runId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/agent-runs/${encodeURIComponent(runId)}`;
}

export function AgentRunActions({
  canCancel = false,
  canRerun = false,
  organizationId,
  runId,
  variant = "label",
  workspaceId,
}: AgentRunActionsProps) {
  const router = useRouter();
  const [busyAction, setBusyAction] = useState<"cancel" | "rerun" | "">("");
  const iconOnly = variant === "icon";

  async function cancelRun() {
    if (!window.confirm("Cancel this run?")) {
      return;
    }
    setBusyAction("cancel");
    try {
      await workspaceAgentRunsCancel(organizationId, workspaceId, runId);
      router.refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Could not cancel run.");
    } finally {
      setBusyAction("");
    }
  }

  async function rerunRun() {
    if (
      !window.confirm(
        "Rerun this run? Provider-triggered runs will send the new reply to the same thread."
      )
    ) {
      return;
    }
    setBusyAction("rerun");
    try {
      const response = await workspaceAgentRunsRerun(organizationId, workspaceId, runId, {
        timeoutMs: rerunTimeoutMs,
      });
      router.push(runHref(organizationId, workspaceId, response.run.id));
      router.refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Could not rerun run.");
    } finally {
      setBusyAction("");
    }
  }

  if (!canCancel && !canRerun) {
    return null;
  }

  return (
    <>
      {canCancel ? (
        <Button
          aria-label="Cancel run"
          disabled={Boolean(busyAction)}
          onClick={cancelRun}
          size={iconOnly ? "icon" : "sm"}
          title="Cancel run"
          type="button"
          variant="outline"
        >
          {busyAction === "cancel" ? (
            <RefreshCw className="size-4 animate-spin" />
          ) : (
            <X className="size-4" />
          )}
          {iconOnly ? null : "Cancel"}
        </Button>
      ) : null}
      {canRerun ? (
        <Button
          aria-label="Rerun"
          disabled={Boolean(busyAction)}
          onClick={rerunRun}
          size={iconOnly ? "icon" : "sm"}
          title="Rerun"
          type="button"
          variant="outline"
        >
          {busyAction === "rerun" ? (
            <RefreshCw className="size-4 animate-spin" />
          ) : (
            <RotateCcw className="size-4" />
          )}
          {iconOnly ? null : "Rerun"}
        </Button>
      ) : null}
    </>
  );
}
