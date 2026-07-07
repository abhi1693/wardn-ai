"use client";

import { ArrowLeft, Loader2, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
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

import { displayLimitKey, scopeLabel } from "./limit-display";

type DeleteLimitClientProps = {
  limit: ResourceLimitRead;
  organizationId: string;
  organizations: OrganizationRead[];
  workspaces: WorkspaceRead[];
};

function errorMessage(payload: unknown, fallback: string) {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return fallback;
}

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
      const response = await fetch(`/api/limits/${encodeURIComponent(limit.id)}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(errorMessage(payload, "Limit could not be deleted."));
      }
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
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
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
