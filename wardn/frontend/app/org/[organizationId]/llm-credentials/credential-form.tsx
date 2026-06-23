"use client";

import { Check, Copy, KeyRound, Loader2, PlugZap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import { errorMessage } from "../tokens/token-form";
import type {
  CredentialFormProps,
  CredentialPayload,
  CredentialProvider,
  CredentialVisibility,
} from "./types";

const providerOptions: Array<{
  value: CredentialProvider;
  label: string;
  description: string;
  authMethod: "api_key" | "oauth";
}> = [
  {
    value: "openai",
    label: "OpenAI",
    description: "Use an OpenAI API key for model calls.",
    authMethod: "api_key",
  },
  {
    value: "openai_chatgpt",
    label: "OpenAI ChatGPT",
    description: "Connect a ChatGPT account using OAuth.",
    authMethod: "oauth",
  },
];

const visibilityOptions: Array<{
  value: CredentialVisibility;
  label: string;
  description: string;
}> = [
  {
    value: "organization",
    label: "Organization",
    description: "Available across this organization.",
  },
  {
    value: "workspace",
    label: "Workspace",
    description: "Available only inside one workspace.",
  },
  {
    value: "user",
    label: "User",
    description: "Reserved for credentials owned by the signed-in user.",
  },
];

function providerForCredential(credential?: CredentialFormProps["credential"]): CredentialProvider {
  if (credential?.provider === "openai_chatgpt" || credential?.authMethod === "oauth") {
    return "openai_chatgpt";
  }
  return "openai";
}

function authMethodForProvider(provider: CredentialProvider) {
  return provider === "openai_chatgpt" ? "oauth" : "api_key";
}

function shellQuote(value: string) {
  return `'${value.replaceAll("'", "'\"'\"'")}'`;
}

export function CredentialForm({
  credential,
  currentUser,
  organization,
  workspaces,
}: CredentialFormProps) {
  const router = useRouter();
  const isEditing = Boolean(credential);
  const [name, setName] = useState(credential?.name ?? "");
  const [provider, setProvider] = useState<CredentialProvider>(() =>
    providerForCredential(credential)
  );
  const [visibility, setVisibility] = useState<CredentialVisibility>(
    credential?.visibility ?? "organization"
  );
  const [workspaceId, setWorkspaceId] = useState(credential?.workspaceId ?? "");
  const [secret, setSecret] = useState("");
  const [isDefault, setIsDefault] = useState(credential?.isDefault ?? false);
  const [isActive, setIsActive] = useState(credential?.isActive ?? true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeWorkspaces = useMemo(
    () => workspaces.filter((workspace) => workspace.status === "active"),
    [workspaces]
  );

  const canSave =
    name.trim().length > 0 &&
    !isSubmitting &&
    (isEditing || provider !== "openai_chatgpt") &&
    (visibility !== "workspace" || workspaceId.length > 0) &&
    (isEditing || authMethodForProvider(provider) !== "api_key" || secret.trim().length > 0);
  const cliName = name.trim() || "OpenAI ChatGPT";
  const cliWorkspaceId =
    visibility === "workspace" ? workspaceId || "<workspace-id>" : "";
  const cliUserEmail = currentUser?.email ?? "<user-email>";
  const chatgptCommand = [
    "python -m app.manage connectchatgpt",
    "--organization-id",
    shellQuote(organization.id),
    "--user-email",
    shellQuote(cliUserEmail),
    "--name",
    shellQuote(cliName),
    "--visibility",
    shellQuote(visibility),
    ...(visibility === "workspace" ? ["--workspace-id", shellQuote(cliWorkspaceId)] : []),
    ...(isDefault ? ["--default"] : []),
  ].join(" ");

  async function copyChatgptCommand() {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(chatgptCommand);
    } else {
      const field = document.createElement("textarea");
      field.value = chatgptCommand;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.top = "-1000px";
      document.body.appendChild(field);
      field.select();
      document.execCommand("copy");
      document.body.removeChild(field);
    }
    setCopiedCommand(true);
    window.setTimeout(() => setCopiedCommand(false), 1600);
  }

  async function submitCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const payload: CredentialPayload = {
        name: name.trim(),
        provider,
        visibility,
        workspaceId: visibility === "workspace" ? workspaceId : null,
        authMethod: authMethodForProvider(provider),
        baseUrl: "",
        extraHeaders: {},
        isDefault,
        ...(isEditing ? { isActive } : {}),
      };

      if (provider === "openai") {
        if (secret.trim()) {
          payload.secret = secret;
        }
      } else {
        payload.oauthProvider = "chatgpt";
      }

      const response = await fetch(
        credential
          ? `/api/organizations/${organization.id}/llm/provider-credentials/${credential.id}`
          : `/api/organizations/${organization.id}/llm/provider-credentials`,
        {
          method: credential ? "PATCH" : "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      const data = (await response.json().catch(() => null)) as unknown;
      if (!response.ok) {
        throw new Error(errorMessage(data, "Credential could not be saved."));
      }
      router.push(`/org/${organization.id}/llm-credentials`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Credential could not be saved.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div>
              <CardTitle>{isEditing ? "Edit LLM Credential" : "Create LLM Credential"}</CardTitle>
              <CardDescription>
                Configure the provider access agents will use for model calls.
              </CardDescription>
            </div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
              <PlugZap className="size-5" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" onSubmit={submitCredential}>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="credential-provider">Provider</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-70"
                  disabled={isEditing}
                  id="credential-provider"
                  onChange={(event) => setProvider(event.target.value as CredentialProvider)}
                  value={provider}
                >
                  {providerOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="credential-name">Name</Label>
                <Input
                  id="credential-name"
                  maxLength={100}
                  onChange={(event) => setName(event.target.value)}
                  required
                  value={name}
                />
              </div>
            </div>

            {provider === "openai" ? (
              <div className="space-y-2">
                <Label htmlFor="credential-secret">API key</Label>
                <Input
                  autoComplete="off"
                  id="credential-secret"
                  onChange={(event) => setSecret(event.target.value)}
                  placeholder={isEditing ? "Leave blank to keep current key" : ""}
                  required={!isEditing}
                  type="password"
                  value={secret}
                />
              </div>
            ) : (
              <div className="space-y-3 rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4">
                <div className="text-sm text-[var(--on-surface-variant)]">
                  {isEditing
                    ? "This credential is connected through local ChatGPT OAuth."
                    : "Run this command locally on the Wardn backend host to connect ChatGPT."}
                </div>
                {!isEditing ? (
                  <div className="flex gap-2">
                    <code className="block min-h-10 flex-1 rounded-md border border-[var(--outline-variant)] bg-white px-3 py-2 font-mono text-xs leading-5 text-[var(--on-surface)]">
                      {chatgptCommand}
                    </code>
                    <Button
                      aria-label="Copy ChatGPT command"
                      onClick={copyChatgptCommand}
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      {copiedCommand ? (
                        <Check className="size-4" />
                      ) : (
                        <Copy className="size-4" />
                      )}
                    </Button>
                  </div>
                ) : null}
              </div>
            )}

            <div className="space-y-3">
              <Label>Visibility</Label>
              <div className="grid gap-3 md:grid-cols-3">
                {visibilityOptions.map((option) => (
                  <label
                    className={cn(
                      "flex min-h-28 cursor-pointer flex-col justify-between rounded-lg border bg-white p-4 transition-colors",
                      visibility === option.value
                        ? "border-primary ring-2 ring-primary/15"
                        : "border-[var(--outline-variant)] hover:border-primary/40"
                    )}
                    key={option.value}
                  >
                    <span>
                      <span className="flex items-center gap-2 text-sm font-semibold">
                        <input
                          checked={visibility === option.value}
                          className="size-4 accent-primary"
                          name="visibility"
                          onChange={() => setVisibility(option.value)}
                          type="radio"
                        />
                        {option.label}
                      </span>
                      <span className="mt-2 block text-sm leading-5 text-[var(--on-surface-variant)]">
                        {option.description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {visibility === "workspace" ? (
              <div className="space-y-2">
                <Label htmlFor="credential-workspace">Workspace</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  id="credential-workspace"
                  onChange={(event) => setWorkspaceId(event.target.value)}
                  required
                  value={workspaceId}
                >
                  <option value="">Select workspace</option>
                  {activeWorkspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <div className="grid gap-3 md:grid-cols-2">
              <label className="flex min-h-10 items-center gap-3 rounded-md border border-[var(--outline-variant)] px-3 text-sm">
                <input
                  checked={isDefault}
                  className="size-4 accent-primary"
                  onChange={(event) => setIsDefault(event.target.checked)}
                  type="checkbox"
                />
                Default credential
              </label>
              {isEditing ? (
                <label className="flex min-h-10 items-center gap-3 rounded-md border border-[var(--outline-variant)] px-3 text-sm">
                  <input
                    checked={isActive}
                    className="size-4 accent-primary"
                    onChange={(event) => setIsActive(event.target.checked)}
                    type="checkbox"
                  />
                  Active
                </label>
              ) : null}
            </div>

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button asChild type="button" variant="outline">
                <Link href={`/org/${organization.id}/llm-credentials`}>Cancel</Link>
              </Button>
              {provider === "openai_chatgpt" && !isEditing ? null : (
                <Button disabled={!canSave} type="submit">
                  {isSubmitting ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : isEditing ? (
                    <Check />
                  ) : (
                    <KeyRound />
                  )}
                  {isEditing ? "Save changes" : "Create credential"}
                </Button>
              )}
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
