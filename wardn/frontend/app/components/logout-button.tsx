"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";

export function LogoutButton() {
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
    <Button disabled={isSubmitting} onClick={handleLogout} size="sm" type="button" variant="outline">
      <LogOut className="size-4" />
      {isSubmitting ? "Signing out" : "Sign out"}
    </Button>
  );
}
