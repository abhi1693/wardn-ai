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
import type { OrganizationRead } from "@/lib/api/generated/model";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type OrganizationFormProps = {
  initialOrganization?: OrganizationRead;
  mode: "create" | "edit";
};

function slugify(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function setSelectionCookie(name: string, value: string, maxAge = 31536000) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; samesite=lax`;
}

export function OrganizationForm({ initialOrganization, mode }: OrganizationFormProps) {
  const router = useRouter();
  const [name, setName] = useState(initialOrganization?.name ?? "");
  const [slug, setSlug] = useState(initialOrganization?.slug ?? "");
  const [status, setStatus] = useState(initialOrganization?.status ?? "active");
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
        ? "/api/organizations"
        : `/api/organizations/${encodeURIComponent(initialOrganization?.id ?? "")}`,
      {
        method: mode === "create" ? "POST" : "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          mode === "create"
            ? { name: name.trim(), slug: slug.trim() }
            : { name: name.trim(), status }
        ),
      }
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(typeof payload?.detail === "string" ? payload.detail : "Organization could not be saved.");
      setSubmitting(false);
      return;
    }
    const organization = (await response.json()) as OrganizationRead;
    setSelectionCookie(selectedOrganizationCookie, organization.id);
    setSelectionCookie(selectedWorkspaceCookie, "", 0);
    router.push(`/org/${encodeURIComponent(organization.id)}/workspaces`);
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
          <CardTitle>Organization</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid max-w-2xl gap-2">
            <Label htmlFor="organization-name">Name</Label>
            <Input
              id="organization-name"
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
            <Label htmlFor="organization-slug">Slug</Label>
            <Input
              disabled={mode === "edit"}
              id="organization-slug"
              onChange={(event) => setSlug(slugify(event.target.value))}
              value={slug}
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
                  <SelectItem value="suspended">Suspended</SelectItem>
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
