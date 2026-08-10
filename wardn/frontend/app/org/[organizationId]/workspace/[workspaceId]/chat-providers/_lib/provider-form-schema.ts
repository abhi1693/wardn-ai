import { z } from "zod";

import type { FormIssue } from "@/components/molecules/form-error-summary";

const providerFormSchema = z
  .object({
    botToken: z.string(),
    bridgeBaseUrl: z.string(),
    bridgeUserId: z.string(),
    missingApprovalLinks: z.number().int().min(0),
    mode: z.enum(["create", "edit"]),
    name: z.string().trim().min(1, "Enter a provider name."),
    provider: z.enum(["whatsapp_local", "telegram", "slack"]),
    secretStoreId: z.string(),
    slackAppToken: z.string(),
    webhookSecret: z.string(),
  })
  .superRefine((value, context) => {
    if (value.missingApprovalLinks > 0) {
      context.addIssue({
        code: "custom",
        message: "Select a valid conversation for every approval recipient.",
        path: ["approvalRoutes"],
      });
    }
    if (value.mode === "edit") {
      return;
    }
    if (!value.secretStoreId.trim()) {
      context.addIssue({
        code: "custom",
        message: "Connect and select an active secret backend.",
        path: ["secretStoreId"],
      });
    }
    if (value.provider === "whatsapp_local") {
      if (!value.bridgeBaseUrl.trim()) {
        context.addIssue({
          code: "custom",
          message: "Enter the WhatsApp gateway URL.",
          path: ["bridgeBaseUrl"],
        });
      }
      if (!value.webhookSecret.trim()) {
        context.addIssue({
          code: "custom",
          message: "Generate or enter a webhook secret.",
          path: ["webhookSecret"],
        });
      }
    }
    if (value.provider === "telegram" && !value.botToken.trim()) {
      context.addIssue({
        code: "custom",
        message: "Enter the Telegram bot token.",
        path: ["botToken"],
      });
    }
    if (value.provider === "slack") {
      if (!value.botToken.trim()) {
        context.addIssue({
          code: "custom",
          message: "Enter the Slack bot token.",
          path: ["botToken"],
        });
      }
      if (!value.slackAppToken.trim()) {
        context.addIssue({
          code: "custom",
          message: "Enter the Slack app-level token.",
          path: ["slackAppToken"],
        });
      }
      if (!/^T[A-Z0-9]+$/.test(value.bridgeUserId.trim())) {
        context.addIssue({
          code: "custom",
          message: "Enter a Slack team ID beginning with T.",
          path: ["bridgeUserId"],
        });
      }
    }
  });

const fieldMetadata: Record<string, { fieldId: string; label: string }> = {
  approvalRoutes: { fieldId: "chat-provider-approval-routes", label: "Approval routes" },
  botToken: { fieldId: "chat-provider-bot-token", label: "Bot token" },
  bridgeBaseUrl: { fieldId: "chat-provider-bridge", label: "WhatsApp gateway URL" },
  bridgeUserId: { fieldId: "chat-provider-external", label: "External account" },
  name: { fieldId: "chat-provider-name", label: "Name" },
  secretStoreId: { fieldId: "chat-provider-secret-store", label: "Secret backend" },
  slackAppToken: { fieldId: "chat-provider-webhook-secret", label: "App-level token" },
  webhookSecret: { fieldId: "chat-provider-webhook-secret", label: "Webhook secret" },
};

export type ProviderFormValidationValues = z.input<typeof providerFormSchema>;

export function providerFormIssues(values: ProviderFormValidationValues): FormIssue[] {
  const result = providerFormSchema.safeParse(values);
  if (result.success) {
    return [];
  }
  return result.error.issues.map((issue) => {
    const key = String(issue.path[0] ?? "name");
    const metadata = fieldMetadata[key] ?? fieldMetadata.name;
    return { ...metadata, message: issue.message };
  });
}
