"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/atoms/button";
import type { buttonVariants } from "@/components/atoms/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/atoms/tooltip";
import { authLogout } from "@/lib/api/generated/auth/auth";
import { confirmActiveFormNavigation } from "@/hooks/use-unsaved-changes";
import type { VariantProps } from "class-variance-authority";

type LogoutButtonProps = {
  className?: string;
  iconOnly?: boolean;
} & Pick<VariantProps<typeof buttonVariants>, "variant">;

export function LogoutButton({ className, iconOnly = false, variant }: LogoutButtonProps) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleLogout() {
    if (!confirmActiveFormNavigation()) {
      return;
    }
    setIsSubmitting(true);
    await authLogout();
    router.replace("/login");
    router.refresh();
  }

  const button = (
    <Button
      aria-label="Sign out"
      disabled={isSubmitting}
      onClick={handleLogout}
      className={className}
      size={iconOnly ? "icon" : "sm"}
      type="button"
      variant={variant ?? (iconOnly ? "ghost" : "outline")}
    >
      <LogOut className="size-4" />
      {iconOnly ? null : isSubmitting ? "Signing out" : "Sign out"}
    </Button>
  );

  if (!iconOnly) {
    return button;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="bottom">Sign out</TooltipContent>
    </Tooltip>
  );
}
