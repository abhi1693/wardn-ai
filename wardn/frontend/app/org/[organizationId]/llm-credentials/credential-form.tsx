"use client";

import { Check, CheckCircle2, Copy, KeyRound, Loader2, PlugZap, ShieldCheck } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  if (/^[A-Za-z0-9_./:@%+=,-]+$/.test(value)) {
    return value;
  }
  return `'${value.replace(/'/g, "'\\''")}'`;
}

export function CredentialForm({
  credential,
  currentUser,
  organization,
  secretStores,
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
  const [apiKey, setApiKey] = useState("");
  const [selectedSecretStoreId, setSelectedSecretStoreId] = useState("");
  const [isActive, setIsActive] = useState(credential?.isActive ?? true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const activeWorkspaces = useMemo(
    () => workspaces.filter((workspace) => workspace.status === "active"),
    [workspaces]
  );
  const isChatgptCredential = provider === "openai_chatgpt";
  const isChatgptConnectorCreate = isChatgptCredential && !isEditing;
  const credentialId = credential?.id ?? "";
  const availableSecretStores = useMemo(() => {
    const activeStores = secretStores.filter((store) => store.isActive);
    if (visibility === "workspace" && workspaceId) {
      return activeStores.filter(
        (store) => !store.workspaceId || store.workspaceId === workspaceId
      );
    }
    return activeStores.filter((store) => !store.workspaceId);
  }, [secretStores, visibility, workspaceId]);
  const preferredSecretStore = useMemo(() => {
    if (visibility === "workspace" && workspaceId) {
      return (
        availableSecretStores.find((store) => store.workspaceId === workspaceId) ??
        availableSecretStores.find((store) => !store.workspaceId) ??
        availableSecretStores[0] ??
        null
      );
    }
    return (
      availableSecretStores.find((store) => !store.workspaceId) ??
      availableSecretStores[0] ??
      null
    );
  }, [availableSecretStores, visibility, workspaceId]);
  const effectiveSecretStoreId =
    selectedSecretStoreId &&
    availableSecretStores.some((store) => store.id === selectedSecretStoreId)
      ? selectedSecretStoreId
      : preferredSecretStore?.id ?? availableSecretStores[0]?.id ?? "";
  const hasCredentialName = name.trim().length > 0;

  const canSave =
    hasCredentialName &&
    !isSubmitting &&
    (visibility !== "workspace" || workspaceId.length > 0) &&
    (provider === "openai"
      ? isEditing
        ? true
        : apiKey.trim().length > 0 && effectiveSecretStoreId.length > 0
      : !isChatgptConnectorCreate);

  const chatgptCommand = useMemo(() => {
    if (!isChatgptCredential) {
      return "";
    }
    if (!isEditing && !hasCredentialName) {
      return "";
    }

    const command = [
      "cd wardn/backend",
      "&&",
      "../../.venv/bin/python",
      "-m",
      "app.manage",
      "connectchatgpt",
      "--organization-id",
      shellQuote(organization.id),
      "--user-email",
      shellQuote(currentUser?.email ?? "<user-email>"),
    ];

    if (credentialId) {
      command.push("--credential-id", shellQuote(credentialId));
    } else {
      command.push(
        "--secret-store-id",
        shellQuote(effectiveSecretStoreId || "<secret-store-id>"),
        "--name",
        shellQuote(name.trim()),
        "--visibility",
        shellQuote(visibility)
      );
      if (visibility === "workspace") {
        command.push("--workspace-id", shellQuote(workspaceId || "<workspace-id>"));
      }
    }
    return command.join(" ");
  }, [
    credentialId,
    currentUser?.email,
    effectiveSecretStoreId,
    hasCredentialName,
    isChatgptCredential,
    isEditing,
    name,
    organization.id,
    visibility,
    workspaceId,
  ]);

  async function copyChatgptCommand() {
    if (!chatgptCommand) {
      return;
    }

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
    window.setTimeout(() => setCopiedCommand(false), 1500);
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
        ...(isEditing ? { isActive } : {}),
      };

      if (provider === "openai") {
        if (!isEditing) {
          payload.apiKeySecretStoreId = effectiveSecretStoreId;
          payload.apiKey = apiKey.trim();
        }
      } else if (!isEditing) {
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

  async function validateCredential() {
    if (!credential || isValidating) {
      return;
    }

    setIsValidating(true);
    setError(null);
    setNotice(null);

    try {
      const response = await fetch(
        `/api/organizations/${organization.id}/llm/provider-credentials/${credential.id}/validate`,
        { method: "POST" }
      );
      const data = (await response.json().catch(() => null)) as unknown;
      if (!response.ok) {
        throw new Error(errorMessage(data, "Credential validation failed."));
      }
      const result = data as { ok?: unknown; message?: unknown };
      const message =
        typeof result.message === "string" && result.message.trim().length > 0
          ? result.message
          : "Credential validation failed.";
      if (result.ok !== true) {
        throw new Error(message);
      }
      setNotice(message);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Credential validation failed.");
    } finally {
      setIsValidating(false);
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
              isEditing ? null : (
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="credential-api-key-secret-store">Secret backend</Label>
                    {availableSecretStores.length > 0 ? (
                      <Select
                        onValueChange={setSelectedSecretStoreId}
                        value={effectiveSecretStoreId}
                      >
                        <SelectTrigger id="credential-api-key-secret-store">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {availableSecretStores.map((store) => (
                            <SelectItem key={store.id} value={store.id}>
                              {store.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        disabled
                        id="credential-api-key-secret-store"
                        placeholder="Connect a secret backend first"
                      />
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="credential-api-key">API key</Label>
                    <Input
                      autoComplete="off"
                      id="credential-api-key"
                      onChange={(event) => setApiKey(event.target.value)}
                      required
                      type="password"
                      value={apiKey}
                    />
                  </div>
                </div>
              )
            ) : (
              <div className="space-y-4">
                {!isEditing ? (
                  <div className="space-y-3 rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4">
                    <div className="space-y-2">
                      <Label htmlFor="credential-chatgpt-secret-store">
                        Secret backend
                      </Label>
                      {availableSecretStores.length > 0 ? (
                        <Select
                          onValueChange={setSelectedSecretStoreId}
                          value={effectiveSecretStoreId}
                        >
                          <SelectTrigger id="credential-chatgpt-secret-store">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {availableSecretStores.map((store) => (
                              <SelectItem key={store.id} value={store.id}>
                                {store.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <Input
                          disabled
                          id="credential-chatgpt-secret-store"
                          placeholder="Connect an organization secret backend first"
                        />
                      )}
                    </div>
                    {hasCredentialName ? (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-3">
                          <Label htmlFor="credential-chatgpt-command">
                            ChatGPT connector command
                          </Label>
                          <Button
                            onClick={copyChatgptCommand}
                            size="sm"
                            type="button"
                            variant="outline"
                          >
                            {copiedCommand ? <Check /> : <Copy />}
                            {copiedCommand ? "Copied" : "Copy"}
                          </Button>
                        </div>
                        <pre
                          className="max-h-36 overflow-x-auto rounded-md border border-[var(--outline-variant)] bg-white p-3 text-xs leading-5 text-[var(--on-surface)]"
                          id="credential-chatgpt-command"
                        >
                          <code>{chatgptCommand}</code>
                        </pre>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="space-y-3 rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium">Reconnect ChatGPT</div>
                        <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
                          Run this command to replace the OAuth tokens for this credential.
                        </p>
                      </div>
                      <Button
                        onClick={copyChatgptCommand}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        {copiedCommand ? <Check /> : <Copy />}
                        {copiedCommand ? "Copied" : "Copy"}
                      </Button>
                    </div>
                    <pre
                      className="max-h-36 overflow-x-auto rounded-md border border-[var(--outline-variant)] bg-white p-3 text-xs leading-5 text-[var(--on-surface)]"
                      id="credential-chatgpt-reconnect-command"
                    >
                      <code>{chatgptCommand}</code>
                    </pre>
                  </div>
                )}
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

            {isEditing ? (
              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex min-h-10 items-center gap-3 rounded-md border border-[var(--outline-variant)] px-3 text-sm">
                  <input
                    checked={isActive}
                    className="size-4 accent-primary"
                    onChange={(event) => setIsActive(event.target.checked)}
                    type="checkbox"
                  />
                  Active
                </label>
              </div>
            ) : null}

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}
            {notice ? (
              <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                <CheckCircle2 className="size-4" />
                {notice}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button asChild type="button" variant="outline">
                <Link href={`/org/${organization.id}/llm-credentials`}>Cancel</Link>
              </Button>
              {isEditing ? (
                <Button
                  disabled={isValidating}
                  onClick={validateCredential}
                  type="button"
                  variant="outline"
                >
                  {isValidating ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <ShieldCheck className="size-4" />
                  )}
                  {isValidating ? "Validating" : "Validate"}
                </Button>
              ) : null}
              {isChatgptConnectorCreate ? null : (
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
