"use client";

import { ArrowLeft, Loader2, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  OrganizationRead,
  ResourceLimitRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { limitsDelete } from "@/lib/api/generated/limits/limits";

import { displayLimitKey, scopeLabel } from "./limit-display";

type DeleteLimitClientProps = {
  limit: ResourceLimitRead;
  organizationId: string;
  organizations: OrganizationRead[];
  workspaces: WorkspaceRead[];
};

export function DeleteLimitClient({
  limit,
  organizationId,
  organizations,
  workspaces,
}: DeleteLimitClientProps) {
  const router = useRouter();
  const listPath = `/org/${organizationId}/limits`;
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function deleteLimit() {
    setDeleting(true);
    setError(null);
    try {
      await limitsDelete(limit.id);
      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Limit could not be deleted.");
      setDeleting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Delete Limit</CardTitle>
        <CardDescription>
          Delete {displayLimitKey(limit.limitKey)} for{" "}
          {scopeLabel(limit, organizations, workspaces)}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          This action cannot be undone.
        </div>

        {error ? (
          <AsyncFeedback variant="error">{error}</AsyncFeedback>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button asChild variant="outline">
            <Link href={listPath}>
              <ArrowLeft className="size-4" />
              Back
            </Link>
          </Button>
          <Button disabled={deleting} onClick={deleteLimit} type="button" variant="destructive">
            {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 />}
            {deleting ? "Deleting" : "Delete limit"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
