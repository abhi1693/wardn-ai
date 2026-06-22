"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type OpenWorkspaceButtonProps = {
  organizationId: string;
  workspaceId: string;
};

function setSelectionCookie(name: string, value: string) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=31536000; samesite=lax`;
}

export function OpenWorkspaceButton({ organizationId, workspaceId }: OpenWorkspaceButtonProps) {
  const router = useRouter();

  return (
    <Button
      onClick={() => {
        setSelectionCookie(selectedOrganizationCookie, organizationId);
        setSelectionCookie(selectedWorkspaceCookie, workspaceId);
        router.push(
          `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
            workspaceId
          )}/dashboard`
        );
        router.refresh();
      }}
      size="sm"
      type="button"
      variant="outline"
    >
      Open
      <ArrowRight className="size-4" />
    </Button>
  );
}
