"use client";

import { RefreshCw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/atoms/button";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { workspaceScheduledTasksCancelRun } from "@/lib/api/generated/workspace-scheduled-tasks/workspace-scheduled-tasks";

type CancelScheduledTaskRunButtonProps = {
  canCancel: boolean;
  organizationId: string;
  runId: string;
  taskId: string;
  workspaceId: string;
};

export function CancelScheduledTaskRunButton({
  canCancel,
  organizationId,
  runId,
  taskId,
  workspaceId,
}: CancelScheduledTaskRunButtonProps) {
  const router = useRouter();
  const [isCanceling, setIsCanceling] = useState(false);
  const [isCanceled, setIsCanceled] = useState(false);

  if (!canCancel || isCanceled) {
    return null;
  }

  async function cancelRun() {
    setIsCanceling(true);
    try {
      await workspaceScheduledTasksCancelRun(organizationId, workspaceId, taskId, runId);
      setIsCanceled(true);
      router.refresh();
    } finally {
      setIsCanceling(false);
    }
  }

  return (
    <ConfirmActionDialog
      actionLabel="Cancel run"
      description="The current execution will stop. Existing output and delivery records are retained."
      onConfirm={cancelRun}
      title="Cancel this scheduled run?"
      variant="destructive"
    >
      <Button disabled={isCanceling} size="sm" variant="outline">
        {isCanceling ? <RefreshCw className="size-4 animate-spin" /> : <X className="size-4" />}
        Cancel run
      </Button>
    </ConfirmActionDialog>
  );
}
