"use client";

import { RefreshCw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
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
    if (!window.confirm("Cancel this scheduled run?")) {
      return;
    }
    setIsCanceling(true);
    try {
      await workspaceScheduledTasksCancelRun(organizationId, workspaceId, taskId, runId);
      setIsCanceled(true);
      router.refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Could not cancel scheduled run.");
    } finally {
      setIsCanceling(false);
    }
  }

  return (
    <Button disabled={isCanceling} onClick={cancelRun} size="sm" variant="outline">
      {isCanceling ? <RefreshCw className="size-4 animate-spin" /> : <X className="size-4" />}
      Cancel run
    </Button>
  );
}
