import { cloneElement, isValidElement, type ReactElement, type ReactNode, useId } from "react";

import { Label } from "@/components/atoms/label";
import { cn } from "@/lib/utils";

type FormFieldProps = {
  children: ReactElement<Record<string, unknown>>;
  className?: string;
  description?: ReactNode;
  error?: string;
  htmlFor: string;
  label: ReactNode;
  required?: boolean;
};

export function FormField({
  children,
  className,
  description,
  error,
  htmlFor,
  label,
  required = false,
}: FormFieldProps) {
  const generatedId = useId();
  const descriptionId = description ? `${generatedId}-description` : undefined;
  const errorId = error ? `${generatedId}-error` : undefined;
  const describedBy = [descriptionId, errorId].filter(Boolean).join(" ") || undefined;
  const control = isValidElement(children)
    ? cloneElement(children, {
        "aria-describedby": describedBy,
        "aria-invalid": Boolean(error),
      })
    : children;

  return (
    <div className={cn("space-y-2", className)} data-slot="form-field">
      <Label htmlFor={htmlFor}>
        {label}
        {required ? <span className="ml-1 text-destructive">*</span> : null}
      </Label>
      {control}
      {description ? (
        <p className="text-xs leading-5 text-muted-foreground" id={descriptionId}>
          {description}
        </p>
      ) : null}
      {error ? (
        <p className="text-xs font-medium text-destructive" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
