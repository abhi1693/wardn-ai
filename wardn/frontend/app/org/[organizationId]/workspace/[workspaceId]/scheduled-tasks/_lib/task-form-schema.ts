import { z } from "zod";

import type { FormIssue } from "@/components/molecules/form-error-summary";

const taskFormSchema = z.object({
  name: z.string().trim().min(1, "Enter a task name."),
  instructions: z.string().trim().min(1, "Enter instructions for the agent."),
  invalidScheduleCount: z.number().int().max(0, "Fix each incomplete schedule."),
  maxAttempts: z.coerce
    .number()
    .int("Use a whole number of attempts.")
    .min(1, "Use at least one attempt.")
    .max(10, "Use no more than ten attempts."),
  selectedRoutes: z.array(z.string()).min(1, "Select at least one output destination."),
});

const fieldMetadata: Record<string, { fieldId: string; label: string }> = {
  instructions: { fieldId: "scheduled-task-instructions", label: "Prompt" },
  invalidScheduleCount: { fieldId: "scheduled-task-schedule-section", label: "Schedule" },
  maxAttempts: { fieldId: "scheduled-task-max-attempts", label: "Attempts" },
  name: { fieldId: "scheduled-task-name", label: "Task name" },
  selectedRoutes: { fieldId: "scheduled-task-output-section", label: "Output destination" },
};

export type TaskFormValidationValues = z.input<typeof taskFormSchema>;

export function taskFormIssues(values: TaskFormValidationValues): FormIssue[] {
  const result = taskFormSchema.safeParse(values);
  if (result.success) {
    return [];
  }
  return result.error.issues.map((issue) => {
    const key = String(issue.path[0] ?? "name");
    const metadata = fieldMetadata[key] ?? fieldMetadata.name;
    return { ...metadata, message: issue.message };
  });
}
