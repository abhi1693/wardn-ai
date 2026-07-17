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
import type { SecretStoreRead } from "@/lib/api/generated/model";
import { secretStoresDelete } from "@/lib/api/generated/secrets/secrets";

import { secretBackendsPath, type SecretBackendScope } from "./secret-backends-paths";

type SecretBackendDeleteClientProps = SecretBackendScope & {
  store: SecretStoreRead;
};

export function SecretBackendDeleteClient({
  organizationId,
  store,
  workspaceId,
}: SecretBackendDeleteClientProps) {
  const router = useRouter();
  const listPath = secretBackendsPath({ organizationId, workspaceId });
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function deleteBackend() {
    setDeleting(true);
    setError(null);

    try {
      await secretStoresDelete(organizationId, store.id);
      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Secret backend could not be deleted."
      );
      setDeleting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Delete Secret Backend</CardTitle>
        <CardDescription>
          Delete the OpenBao connection named {store.name}. Existing secret handles that use it
          will no longer resolve.
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
          <Button disabled={deleting} onClick={deleteBackend} type="button" variant="destructive">
            {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
            {deleting ? "Deleting" : "Delete backend"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
