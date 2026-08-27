import { AlertCircle } from "lucide-react";

import { cn } from "@/lib/utils";

export type FormIssue = {
  fieldId: string;
  label: string;
  message: string;
};

type FormErrorSummaryProps = {
  className?: string;
  issues: FormIssue[];
  title?: string;
};

export function focusFormIssue(issue: FormIssue | undefined) {
  if (!issue) {
    return;
  }
  window.requestAnimationFrame(() => {
    document.getElementById(issue.fieldId)?.focus();
  });
}

export function focusFirstInvalidFormControl(formId: string, preferredFieldId?: string) {
  window.requestAnimationFrame(() => {
    const form = document.getElementById(formId);
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    const preferred = preferredFieldId ? document.getElementById(preferredFieldId) : null;
    const fallback = form.querySelector<HTMLElement>(
      '[aria-invalid="true"], input:invalid, select:invalid, textarea:invalid'
    );
    const control = preferred instanceof HTMLElement ? preferred : fallback;
    control?.focus();
    control?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

export function FormErrorSummary({
  className,
  issues,
  title = "Review the highlighted fields",
}: FormErrorSummaryProps) {
  if (issues.length === 0) {
    return null;
  }

  return (
    <div
      aria-live="assertive"
      className={cn(
        "rounded-md border border-destructive/35 bg-destructive/5 px-4 py-3 text-sm text-foreground",
        className
      )}
      role="alert"
    >
      <div className="flex items-center gap-2 font-semibold">
        <AlertCircle className="size-4 text-destructive" />
        {title}
      </div>
      <ul className="mt-2 space-y-1 pl-6">
        {issues.map((issue) => (
          <li className="list-disc" key={`${issue.fieldId}-${issue.message}`}>
            <button
              className="text-left text-destructive underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => focusFormIssue(issue)}
              type="button"
            >
              <span className="font-medium">{issue.label}:</span> {issue.message}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
