"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { buttonVariants } from "@/components/ui/button";
import type { VariantProps } from "class-variance-authority";

type LogoutButtonProps = {
  className?: string;
  iconOnly?: boolean;
} & Pick<VariantProps<typeof buttonVariants>, "variant">;

export function LogoutButton({ className, iconOnly = false, variant }: LogoutButtonProps) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleLogout() {
    setIsSubmitting(true);
    await fetch("/api/auth/logout", {
      method: "POST",
    });
    router.replace("/login");
    router.refresh();
  }

  return (
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
}
