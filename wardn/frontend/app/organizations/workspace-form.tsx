"use client";

import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { WorkspaceRead } from "@/lib/api/generated/model";

type WorkspaceFormProps = {
  initialWorkspace?: WorkspaceRead;
  mode: "create" | "edit";
  organizationId: string;
};

function slugify(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function WorkspaceForm({ initialWorkspace, mode, organizationId }: WorkspaceFormProps) {
  const router = useRouter();
  const [name, setName] = useState(initialWorkspace?.name ?? "");
  const [slug, setSlug] = useState(initialWorkspace?.slug ?? "");
  const [description, setDescription] = useState(initialWorkspace?.description ?? "");
  const [status, setStatus] = useState(initialWorkspace?.status ?? "active");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canSave = useMemo(() => name.trim().length > 0 && slug.trim().length > 0, [name, slug]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave || submitting) {
      return;
    }
    setSubmitting(true);
    setError("");

    const response = await fetch(
      mode === "create"
        ? `/api/organizations/${encodeURIComponent(organizationId)}/workspaces`
        : `/api/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
            initialWorkspace?.id ?? ""
          )}`,
      {
        method: mode === "create" ? "POST" : "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          mode === "create"
            ? { name: name.trim(), slug: slug.trim(), description: description.trim() }
            : { name: name.trim(), description: description.trim(), status }
        ),
      }
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(typeof payload?.detail === "string" ? payload.detail : "Workspace could not be saved.");
      setSubmitting(false);
      return;
    }
    router.push(`/organizations/${organizationId}`);
    router.refresh();
  }

  return (
    <form className="space-y-5" onSubmit={submit}>
      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Workspace</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid max-w-2xl gap-2">
            <Label htmlFor="workspace-name">Name</Label>
            <Input
              id="workspace-name"
              onChange={(event) => {
                setName(event.target.value);
                if (mode === "create") {
                  setSlug(slugify(event.target.value));
                }
              }}
              value={name}
            />
          </div>

          <div className="grid max-w-2xl gap-2">
            <Label htmlFor="workspace-slug">Slug</Label>
            <Input
              disabled={mode === "edit"}
              id="workspace-slug"
              onChange={(event) => setSlug(slugify(event.target.value))}
              value={slug}
            />
          </div>

          <div className="grid max-w-3xl gap-2">
            <Label htmlFor="workspace-description">Description</Label>
            <textarea
              className="min-h-28 rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              id="workspace-description"
              onChange={(event) => setDescription(event.target.value)}
              value={description}
            />
          </div>

          {mode === "edit" ? (
            <div className="grid max-w-sm gap-2">
              <Label>Status</Label>
              <Select onValueChange={setStatus} value={status}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="flex justify-end gap-2">
        <Button onClick={() => router.back()} type="button" variant="outline">
          Cancel
        </Button>
        <Button disabled={!canSave || submitting} type="submit">
          <Save className="size-4" />
          Save
        </Button>
      </div>
    </form>
  );
}
