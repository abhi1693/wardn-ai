"use client";

import { Loader2 } from "lucide-react";
import { type ReactElement, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/atoms/alert-dialog";
import { MutationErrorDetails } from "@/components/providers/mutation-feedback-provider";

type ConfirmActionDialogProps = {
  actionLabel: string;
  busyLabel?: string;
  children: ReactElement;
  description: string;
  onConfirm: () => Promise<void> | void;
  title: string;
  variant?: "default" | "destructive";
};

export function ConfirmActionDialog({
  actionLabel,
  busyLabel = "Working...",
  children,
  description,
  onConfirm,
  title,
  variant = "default",
}: ConfirmActionDialogProps) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function confirm(event: React.MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      setOpen(false);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught : new Error("The action could not be completed.")
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <AlertDialog
      onOpenChange={(nextOpen) => {
        if (!pending) {
          setOpen(nextOpen);
          if (!nextOpen) {
            setError(null);
          }
        }
      }}
      open={open}
    >
      <AlertDialogTrigger asChild>{children}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {error ? <MutationErrorDetails error={error} /> : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={confirm}
            variant={variant}
          >
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            {pending ? busyLabel : actionLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
