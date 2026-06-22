"use client";

import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { OrganizationRead } from "@/lib/api/generated/model";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type OrganizationFormProps = {
  formId?: string;
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

export function OrganizationForm({ formId, initialOrganization, mode }: OrganizationFormProps) {
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
    router.push(`/org/${encodeURIComponent(organization.id)}/dashboard`);
    router.refresh();
  }

  const title = mode === "edit" && initialOrganization
    ? `${initialOrganization.name} Settings`
    : "Organization Settings";
  const description = mode === "edit"
    ? "Manage your organization core identity and operational status."
    : "Create the core identity for a new organization.";

  return (
    <form className="mx-auto max-w-4xl space-y-8" id={formId} onSubmit={submit}>
      <div>
        <h2 className="mb-2 text-4xl font-bold leading-[44px] tracking-normal text-[var(--on-surface)]">
          {title}
        </h2>
        <p className="text-sm leading-5 text-[var(--on-surface-variant)]">{description}</p>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <Card className="overflow-hidden rounded-xl border-[var(--outline-variant)] bg-[var(--surface)] shadow-none">
        <CardContent className="space-y-8 p-8">
          <div>
            <Label htmlFor="organization-name">Name</Label>
            <Input
              className="mt-2 h-12 rounded-lg border-[var(--outline-variant)] bg-[var(--surface)] px-4 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20"
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

          <div className="grid grid-cols-1 gap-x-6 gap-y-6 md:grid-cols-2">
            <div>
              <Label htmlFor="organization-slug">Slug</Label>
              <Input
                className="mt-2 h-12 rounded-lg border-[var(--outline-variant)] bg-[var(--surface)] px-4 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20"
                disabled={mode === "edit"}
                id="organization-slug"
                onChange={(event) => setSlug(slugify(event.target.value))}
                value={slug}
              />
            </div>

            {mode === "edit" ? (
              <div>
                <Label>Status</Label>
                <Select onValueChange={setStatus} value={status}>
                  <SelectTrigger className="mt-2 h-12 rounded-lg border-[var(--outline-variant)] bg-[var(--surface)] px-4 shadow-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary/20">
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
          </div>

          <div className="flex items-center justify-end gap-4 border-t border-[var(--outline-variant)] pt-4">
            <Button onClick={() => router.back()} type="button" variant="outline">
              Cancel
            </Button>
            <Button disabled={!canSave || submitting} type="submit">
              <Save className="size-4" />
              {submitting ? "Saving" : "Save"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </form>
  );
}
