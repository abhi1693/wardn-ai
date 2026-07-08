"use client";

import {
  Check,
  CheckCircle2,
  ExternalLink,
  KeyRound,
  Loader2,
  PlugZap,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

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

type ChatgptDeviceFlowTarget =
  | { credentialId: string }
  | {
      name: string;
      secretStoreId: string;
      visibility: CredentialVisibility;
      workspaceId: string | null;
    };

type ChatgptDeviceFlow = {
  deviceAuthId: string;
  userCode: string;
  verificationUrl: string;
  intervalSeconds: number;
  target: ChatgptDeviceFlowTarget;
};

export function CredentialForm({
  credential,
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
  const [isStartingChatgpt, setIsStartingChatgpt] = useState(false);
  const [isCompletingChatgpt, setIsCompletingChatgpt] = useState(false);
  const [chatgptDeviceFlow, setChatgptDeviceFlow] = useState<ChatgptDeviceFlow | null>(null);
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
  const canStartChatgptDeviceFlow =
    isChatgptCredential &&
    hasCredentialName &&
    !isStartingChatgpt &&
    !isCompletingChatgpt &&
    (isEditing || effectiveSecretStoreId.length > 0) &&
    (visibility !== "workspace" || workspaceId.length > 0);

  const canSave =
    hasCredentialName &&
    !isSubmitting &&
    (visibility !== "workspace" || workspaceId.length > 0) &&
    (provider === "openai"
      ? isEditing
        ? true
        : apiKey.trim().length > 0 && effectiveSecretStoreId.length > 0
      : !isChatgptConnectorCreate);

  const completeChatgptDeviceFlow = useCallback(async (flow: ChatgptDeviceFlow) => {
    if (isCompletingChatgpt) {
      return;
    }
    setIsCompletingChatgpt(true);
    setError(null);

    try {
      const response = await fetch(
        `/api/organizations/${organization.id}/llm/provider-credentials/chatgpt/device/complete`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            deviceAuthId: flow.deviceAuthId,
            userCode: flow.userCode,
            ...flow.target,
          }),
        }
      );
      const data = (await response.json().catch(() => null)) as unknown;
      if (!response.ok) {
        throw new Error(errorMessage(data, "ChatGPT connection could not be completed."));
      }
      const result = data as { status?: unknown };
      if (result.status === "pending") {
        return;
      }
      if (result.status !== "connected") {
        throw new Error("ChatGPT connection returned an unexpected response.");
      }
      setChatgptDeviceFlow(null);
      if (isEditing) {
        setNotice("ChatGPT credential reconnected.");
        router.refresh();
      } else {
        router.push(`/org/${organization.id}/llm-credentials`);
      }
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "ChatGPT connection could not be completed."
      );
    } finally {
      setIsCompletingChatgpt(false);
    }
  }, [isCompletingChatgpt, isEditing, organization.id, router]);

  async function startChatgptDeviceFlow() {
    if (!canStartChatgptDeviceFlow) {
      return;
    }

    setIsStartingChatgpt(true);
    setChatgptDeviceFlow(null);
    setError(null);
    setNotice(null);

    try {
      const response = await fetch(
        `/api/organizations/${organization.id}/llm/provider-credentials/chatgpt/device/start`,
        { method: "POST" }
      );
      const data = (await response.json().catch(() => null)) as unknown;
      if (!response.ok) {
        throw new Error(errorMessage(data, "ChatGPT connection could not be started."));
      }
      const result = data as {
        deviceAuthId?: unknown;
        userCode?: unknown;
        verificationUrl?: unknown;
        intervalSeconds?: unknown;
      };
      if (
        typeof result.deviceAuthId !== "string" ||
        typeof result.userCode !== "string" ||
        typeof result.verificationUrl !== "string"
      ) {
        throw new Error("ChatGPT connection returned an invalid device code.");
      }
      setChatgptDeviceFlow({
        deviceAuthId: result.deviceAuthId,
        userCode: result.userCode,
        verificationUrl: result.verificationUrl,
        intervalSeconds:
          typeof result.intervalSeconds === "number" && result.intervalSeconds > 0
            ? result.intervalSeconds
            : 5,
        target: credentialId
          ? { credentialId }
          : {
              name: name.trim(),
              secretStoreId: effectiveSecretStoreId,
              visibility,
              workspaceId: visibility === "workspace" ? workspaceId : null,
            },
      });
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "ChatGPT connection could not be started."
      );
    } finally {
      setIsStartingChatgpt(false);
    }
  }

  useEffect(() => {
    if (!chatgptDeviceFlow || isCompletingChatgpt) {
      return;
    }
    const timeout = window.setTimeout(() => {
      void completeChatgptDeviceFlow(chatgptDeviceFlow);
    }, Math.max(chatgptDeviceFlow.intervalSeconds, 2) * 1000);
    return () => window.clearTimeout(timeout);
  }, [chatgptDeviceFlow, completeChatgptDeviceFlow, isCompletingChatgpt]);

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
                    <div className="space-y-3 rounded-md border border-[var(--outline-variant)] bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium">ChatGPT device code</span>
                            <span className="inline-flex items-center gap-1 rounded-md border border-[var(--outline-variant)] px-2 py-1 text-xs font-medium text-[var(--on-surface-variant)]">
                              <PlugZap className="h-3.5 w-3.5" />
                              Browser auth
                            </span>
                          </div>
                          <p className="text-sm text-[var(--on-surface-variant)]">
                            Open ChatGPT, enter the code, and Wardn will finish this credential.
                          </p>
                        </div>
                        {chatgptDeviceFlow ? (
                          <Button asChild type="button" variant="outline">
                            <a
                              href={chatgptDeviceFlow.verificationUrl}
                              rel="noreferrer"
                              target="_blank"
                            >
                              <ExternalLink className="size-4" />
                              Open ChatGPT
                            </a>
                          </Button>
                        ) : (
                          <Button
                            disabled={!canStartChatgptDeviceFlow}
                            onClick={startChatgptDeviceFlow}
                            type="button"
                          >
                            {isStartingChatgpt ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <PlugZap className="size-4" />
                            )}
                            Connect ChatGPT
                          </Button>
                        )}
                      </div>
                      {chatgptDeviceFlow ? (
                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                          <div className="rounded-md border border-[var(--outline-variant)] bg-[var(--surface-container-low)] px-4 py-3">
                            <div className="font-mono text-2xl font-semibold tracking-normal text-[var(--on-surface)]">
                              {chatgptDeviceFlow.userCode}
                            </div>
                          </div>
                          <Button
                            disabled={isCompletingChatgpt}
                            onClick={() => completeChatgptDeviceFlow(chatgptDeviceFlow)}
                            type="button"
                            variant="outline"
                          >
                            {isCompletingChatgpt ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Check className="size-4" />
                            )}
                            {isCompletingChatgpt ? "Checking" : "Check status"}
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3 rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="text-sm font-medium">Reconnect ChatGPT</div>
                          <span className="inline-flex items-center gap-1 rounded-md border border-[var(--outline-variant)] bg-white px-2 py-1 text-xs font-medium text-[var(--on-surface-variant)]">
                            <PlugZap className="h-3.5 w-3.5" />
                            Device code
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
                          Open ChatGPT, enter the code, and Wardn will replace the stored tokens.
                        </p>
                      </div>
                      {chatgptDeviceFlow ? (
                        <Button asChild type="button" variant="outline">
                          <a
                            href={chatgptDeviceFlow.verificationUrl}
                            rel="noreferrer"
                            target="_blank"
                          >
                            <ExternalLink className="size-4" />
                            Open ChatGPT
                          </a>
                        </Button>
                      ) : (
                        <Button
                          disabled={!canStartChatgptDeviceFlow}
                          onClick={startChatgptDeviceFlow}
                          type="button"
                        >
                          {isStartingChatgpt ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <PlugZap className="size-4" />
                          )}
                          Reconnect ChatGPT
                        </Button>
                      )}
                    </div>
                    {chatgptDeviceFlow ? (
                      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                        <div className="rounded-md border border-[var(--outline-variant)] bg-white px-4 py-3">
                          <div className="font-mono text-2xl font-semibold tracking-normal text-[var(--on-surface)]">
                            {chatgptDeviceFlow.userCode}
                          </div>
                        </div>
                        <Button
                          disabled={isCompletingChatgpt}
                          onClick={() => completeChatgptDeviceFlow(chatgptDeviceFlow)}
                          type="button"
                          variant="outline"
                        >
                          {isCompletingChatgpt ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <Check className="size-4" />
                          )}
                          {isCompletingChatgpt ? "Checking" : "Check status"}
                        </Button>
                      </div>
                    ) : null}
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
