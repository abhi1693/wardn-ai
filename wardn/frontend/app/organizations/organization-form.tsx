"use client";

import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { OrganizationRead, OrganizationUpdateStatus } from "@/lib/api/generated/model";
import {
  organizationsCreate,
  organizationsUpdate,
} from "@/lib/api/generated/organizations/organizations";
import { clearSelectionCookie, setSelectionCookie } from "@/lib/selection-cookies";
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

export function OrganizationForm({ formId, initialOrganization, mode }: OrganizationFormProps) {
  const router = useRouter();
  const [name, setName] = useState(initialOrganization?.name ?? "");
  const [slug, setSlug] = useState(initialOrganization?.slug ?? "");
  const [status, setStatus] = useState<OrganizationUpdateStatus>(
    (initialOrganization?.status as OrganizationUpdateStatus) ?? "active"
  );
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

    let organization: OrganizationRead;
    try {
      organization =
        mode === "create"
          ? await organizationsCreate({ name: name.trim(), slug: slug.trim() })
          : await organizationsUpdate(initialOrganization?.id ?? "", {
              name: name.trim(),
              status,
            });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Organization could not be saved.");
      setSubmitting(false);
      return;
    }
    setSelectionCookie(selectedOrganizationCookie, organization.id);
    clearSelectionCookie(selectedWorkspaceCookie);
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
        <AsyncFeedback className="rounded-lg px-4 py-3" variant="error">
          {error}
        </AsyncFeedback>
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
                <Select
                  onValueChange={(value) => setStatus(value as OrganizationUpdateStatus)}
                  value={status}
                >
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
