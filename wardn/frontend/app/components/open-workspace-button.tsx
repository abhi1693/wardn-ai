"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { setSelectionCookie } from "@/lib/selection-cookies";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type OpenWorkspaceButtonProps = {
  organizationId: string;
  workspaceId: string;
};

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
          )}/chat`
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
