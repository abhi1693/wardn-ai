"use client";

import { MessageSquare, MoreHorizontal, RefreshCw, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/atoms/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/atoms/dropdown-menu";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import {
  workspaceAgentRunsCancel,
  workspaceAgentRunsRerun,
} from "@/lib/api/generated/workspace-agent-runs/workspace-agent-runs";

const rerunTimeoutMs = 10 * 60_000;

type AgentRunActionsProps = {
  canCancel?: boolean;
  canRerun?: boolean;
  chatHref?: string;
  organizationId: string;
  runId: string;
  variant?: "icon" | "label" | "menu";
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
  chatHref,
  organizationId,
  runId,
  variant = "label",
  workspaceId,
}: AgentRunActionsProps) {
  const router = useRouter();
  const [busyAction, setBusyAction] = useState<"cancel" | "rerun" | "">("");
  const [confirmation, setConfirmation] = useState<"cancel" | "rerun" | "">("");
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

  if (!canCancel && !canRerun && !chatHref) {
    return null;
  }

  if (variant === "menu") {
    return (
      <>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              aria-label={`More actions for ${runId}`}
              disabled={Boolean(busyAction)}
              size="icon"
              title="More actions"
              type="button"
              variant="outline"
            >
              {busyAction ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : (
                <MoreHorizontal className="size-4" />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            {chatHref ? (
              <DropdownMenuItem asChild>
                <Link href={chatHref}>
                  <MessageSquare className="size-4" />
                  Open chat
                </Link>
              </DropdownMenuItem>
            ) : null}
            {canRerun ? (
              <DropdownMenuItem onSelect={() => setConfirmation("rerun")}>
                <RotateCcw className="size-4" />
                Rerun
              </DropdownMenuItem>
            ) : null}
            {canCancel ? <DropdownMenuSeparator /> : null}
            {canCancel ? (
              <DropdownMenuItem
                onSelect={() => setConfirmation("cancel")}
                variant="destructive"
              >
                <X className="size-4" />
                Cancel run
              </DropdownMenuItem>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
        <ConfirmActionDialog
          actionLabel="Cancel run"
          description="The agent will stop after its current operation. Completed work is retained."
          onConfirm={cancelRun}
          onOpenChange={(open) => setConfirmation(open ? "cancel" : "")}
          open={confirmation === "cancel"}
          title="Cancel this run?"
          variant="destructive"
        />
        <ConfirmActionDialog
          actionLabel="Rerun"
          description="Provider-triggered runs will send the new reply to the same thread."
          onConfirm={rerunRun}
          onOpenChange={(open) => setConfirmation(open ? "rerun" : "")}
          open={confirmation === "rerun"}
          title="Rerun this run?"
        />
      </>
    );
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
