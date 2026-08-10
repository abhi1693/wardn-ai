"use client";

import { AlertTriangle, KeyRound, Loader2, PlugZap, RotateCcw, Settings, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/atoms/button";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { workspaceAgentsQuickStart } from "@/lib/api/generated/workspace-agents/workspace-agents";

type WorkspaceChatLauncherProps = {
  organizationId: string;
  workspaceId: string;
};

export function WorkspaceChatLauncher({ organizationId, workspaceId }: WorkspaceChatLauncherProps) {
  const router = useRouter();
  const started = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(true);
  const workspaceBasePath = `/org/${encodeURIComponent(
    organizationId
  )}/workspace/${encodeURIComponent(workspaceId)}`;

  const startChat = useCallback(async () => {
    setError(null);
    setIsStarting(true);
    try {
      const response = await workspaceAgentsQuickStart(organizationId, workspaceId);
      router.replace(`${workspaceBasePath}/chat/${encodeURIComponent(response.conversation.id)}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Workspace chat could not be started.");
      setIsStarting(false);
    }
  }, [organizationId, router, workspaceBasePath, workspaceId]);

  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;
    void startChat();
  }, [startChat]);

  if (isStarting) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center bg-background">
        <div className="text-center" role="status">
          <div className="mx-auto flex size-11 items-center justify-center rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
          <div className="mt-4 text-sm font-medium text-foreground">Starting workspace chat</div>
          <div className="mt-1 text-xs text-muted-foreground">Loading the assistant and conversation.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[420px] items-center justify-center bg-background p-8">
      <div className="w-full max-w-2xl">
        <div className="mb-5 flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300">
            <AlertTriangle className="size-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-foreground">Chat could not start</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Check the workspace setup, then retry without leaving this page.
            </p>
          </div>
        </div>
        {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
        <div className="mt-5 grid grid-cols-2 gap-3">
          <Button asChild className="justify-start" variant="outline">
            <Link href={`/org/${encodeURIComponent(organizationId)}/llm-credentials`}>
              <KeyRound className="size-4" />
              Credentials
            </Link>
          </Button>
          <Button asChild className="justify-start" variant="outline">
            <Link href={`${workspaceBasePath}/install`}>
              <PlugZap className="size-4" />
              Connections
            </Link>
          </Button>
          <Button asChild className="justify-start" variant="outline">
            <Link href={`${workspaceBasePath}/guardrails`}>
              <ShieldCheck className="size-4" />
              Access rules
            </Link>
          </Button>
          <Button asChild className="justify-start" variant="outline">
            <Link href={`/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(workspaceId)}/settings`}>
              <Settings className="size-4" />
              Workspace settings
            </Link>
          </Button>
        </div>
        <Button className="mt-5" onClick={() => void startChat()}>
          <RotateCcw className="size-4" />
          Retry
        </Button>
      </div>
    </div>
  );
}
