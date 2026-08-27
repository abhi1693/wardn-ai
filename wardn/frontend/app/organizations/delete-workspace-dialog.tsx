"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { type ReactElement, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/atoms/alert-dialog";
import { Button } from "@/components/atoms/button";
import { Input } from "@/components/atoms/input";
import { Label } from "@/components/atoms/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import type { WorkspaceRead } from "@/lib/api/generated/model";
import { workspacesDelete } from "@/lib/api/generated/organizations/organizations";
import { clearSelectionCookie, setSelectionCookie } from "@/lib/selection-cookies";
import { selectedWorkspaceCookie } from "@/lib/workspace-types";

type DeleteWorkspaceDialogProps = {
  isDefaultWorkspace?: boolean;
  organizationId: string;
  replacementWorkspaces?: WorkspaceRead[];
  trigger?: ReactElement;
  workspace: WorkspaceRead;
};

export function DeleteWorkspaceDialog({
  isDefaultWorkspace = false,
  organizationId,
  replacementWorkspaces = [],
  trigger,
  workspace,
}: DeleteWorkspaceDialogProps) {
  const router = useRouter();
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [replacementWorkspaceId, setReplacementWorkspaceId] = useState("");
  const eligibleReplacements = replacementWorkspaces.filter(
    (candidate) =>
      candidate.id !== workspace.id &&
      candidate.status === "active" &&
      (candidate.currentUserRole === "owner" || candidate.currentUserRole === "admin")
  );
  const confirmed =
    confirmation === workspace.name && (!isDefaultWorkspace || Boolean(replacementWorkspaceId));

  async function deleteWorkspace(event: React.MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    if (!confirmed || deleting) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await workspacesDelete(
        organizationId,
        workspace.id,
        isDefaultWorkspace ? { replacementWorkspaceId } : undefined
      );
      if (isDefaultWorkspace) {
        setSelectionCookie(selectedWorkspaceCookie, replacementWorkspaceId);
      } else {
        clearSelectionCookie(selectedWorkspaceCookie);
      }
      setOpen(false);
      router.push(`/org/${encodeURIComponent(organizationId)}/workspaces`);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Workspace could not be deleted.");
      setDeleting(false);
    }
  }

  return (
    <AlertDialog
      onOpenChange={(nextOpen) => {
        if (deleting) {
          return;
        }
        setOpen(nextOpen);
        if (!nextOpen) {
          setConfirmation("");
          setError("");
          setReplacementWorkspaceId("");
        }
      }}
      open={open}
    >
      <AlertDialogTrigger asChild>
        {trigger ?? (
          <Button type="button" variant="destructive">
            <Trash2 className="size-4" />
            Delete workspace
          </Button>
        )}
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {workspace.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently deletes the workspace and its workspace-scoped data. This action
            cannot be undone.
            {isDefaultWorkspace ? " Choose which workspace becomes the new default." : ""}
          </AlertDialogDescription>
        </AlertDialogHeader>

        {isDefaultWorkspace ? (
          <div className="grid gap-2 py-2">
            <Label htmlFor={`replacement-workspace-${workspace.id}`}>New default workspace</Label>
            <Select
              disabled={deleting || eligibleReplacements.length === 0}
              onValueChange={setReplacementWorkspaceId}
              value={replacementWorkspaceId}
            >
              <SelectTrigger id={`replacement-workspace-${workspace.id}`}>
                <SelectValue
                  placeholder={
                    eligibleReplacements.length === 0
                      ? "No eligible workspace available"
                      : "Select a workspace"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {eligibleReplacements.map((candidate) => (
                  <SelectItem key={candidate.id} value={candidate.id}>
                    {candidate.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {eligibleReplacements.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Create or reactivate another workspace before deleting this default workspace.
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="grid gap-2 py-2">
          <Label htmlFor={`delete-workspace-${workspace.id}`}>
            Type <span className="font-semibold text-foreground">{workspace.name}</span> to confirm
          </Label>
          <Input
            autoComplete="off"
            disabled={deleting}
            id={`delete-workspace-${workspace.id}`}
            onChange={(event) => setConfirmation(event.target.value)}
            value={confirmation}
          />
        </div>

        {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!confirmed || deleting}
            onClick={deleteWorkspace}
            variant="destructive"
          >
            {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
            {deleting ? "Deleting..." : "Delete workspace"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
