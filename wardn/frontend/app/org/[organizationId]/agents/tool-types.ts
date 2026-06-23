import type { AgentToolListResponse } from "@/lib/api/generated/model";

export const ALL_SERVER_TOOLS = "*";

export type AgentAvailableTool = {
  annotations?: Record<string, unknown>;
  configName: string;
  description: string;
  inputSchema: Record<string, unknown>;
  installationId: string;
  outputSchema?: Record<string, unknown> | null;
  serverName: string;
  title: string;
  toolName: string;
  toolSchemaId: string;
  workspaceId: string;
};

export type AgentServerToolAssignment = {
  installationId: string;
  toolSchemaIds: string[];
};

export type AgentToolAssignments = {
  servers: AgentServerToolAssignment[];
  tools: AgentToolListResponse["tools"];
};
