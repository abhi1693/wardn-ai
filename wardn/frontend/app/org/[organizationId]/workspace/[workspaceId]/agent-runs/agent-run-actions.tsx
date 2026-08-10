"use client";

import { RefreshCw, RotateCcw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/atoms/button";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
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
    setBusyAction("cancel");
    try {
      await workspaceAgentRunsCancel(organizationId, workspaceId, runId);
      router.refresh();
    } finally {
      setBusyAction("");
    }
  }

  async function rerunRun() {
    setBusyAction("rerun");
    try {
      const response = await workspaceAgentRunsRerun(organizationId, workspaceId, runId, {
        timeoutMs: rerunTimeoutMs,
      });
      router.push(runHref(organizationId, workspaceId, response.run.id));
      router.refresh();
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
        <ConfirmActionDialog
          actionLabel="Cancel run"
          description="The agent will stop after its current operation. Completed work is retained."
          onConfirm={cancelRun}
          title="Cancel this run?"
          variant="destructive"
        >
          <Button
            aria-label="Cancel run"
            disabled={Boolean(busyAction)}
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
        </ConfirmActionDialog>
      ) : null}
      {canRerun ? (
        <ConfirmActionDialog
          actionLabel="Rerun"
          description="Provider-triggered runs will send the new reply to the same thread."
          onConfirm={rerunRun}
          title="Rerun this run?"
        >
          <Button
            aria-label="Rerun"
            disabled={Boolean(busyAction)}
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
        </ConfirmActionDialog>
      ) : null}
    </>
  );
}
