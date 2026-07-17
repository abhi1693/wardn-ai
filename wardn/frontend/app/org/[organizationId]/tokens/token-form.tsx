"use client";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { WorkspaceRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

export type ScopeMode = "organization" | "workspaces";

const scopeOptions: Array<{
  value: ScopeMode;
  label: string;
  description: string;
}> = [
  {
    value: "organization",
    label: "This organization",
    description: "All enabled MCP servers across this organization.",
  },
  {
    value: "workspaces",
    label: "Selected workspaces",
    description: "Only enabled MCP servers in checked workspaces.",
  },
];

function workspaceName(workspaces: WorkspaceRead[], workspaceId: string) {
  return workspaces.find((workspace) => workspace.id === workspaceId)?.name ?? workspaceId;
}

type TokenFieldsProps = {
  activeWorkspaces: WorkspaceRead[];
  description: string;
  expiresAt: string;
  name: string;
  onDescriptionChange: (value: string) => void;
  onExpiresAtChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onScopeModeChange: (value: ScopeMode) => void;
  onWorkspaceToggle: (workspaceId: string) => void;
  scopeMode: ScopeMode;
  selectedWorkspaceIds: Set<string>;
};

export function TokenFields({
  activeWorkspaces,
  description,
  expiresAt,
  name,
  onDescriptionChange,
  onExpiresAtChange,
  onNameChange,
  onScopeModeChange,
  onWorkspaceToggle,
  scopeMode,
  selectedWorkspaceIds,
}: TokenFieldsProps) {
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="token-name">Name</Label>
          <Input
            id="token-name"
            maxLength={100}
            onChange={(event) => onNameChange(event.target.value)}
            required
            value={name}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="token-expires-at">Expires at</Label>
          <Input
            id="token-expires-at"
            onChange={(event) => onExpiresAtChange(event.target.value)}
            type="datetime-local"
            value={expiresAt}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="token-description">Description</Label>
        <Input
          id="token-description"
          maxLength={200}
          onChange={(event) => onDescriptionChange(event.target.value)}
          placeholder="Production agent, local Codex, CI runner"
          value={description}
        />
      </div>

      <div className="space-y-3">
        <Label>Scope</Label>
        <div className="grid gap-3 md:grid-cols-2">
          {scopeOptions.map((option) => (
            <label
              className={cn(
                "flex min-h-28 cursor-pointer flex-col justify-between rounded-lg border bg-white p-4 transition-colors",
                scopeMode === option.value
                  ? "border-primary ring-2 ring-primary/15"
                  : "border-[var(--outline-variant)] hover:border-primary/40"
              )}
              key={option.value}
            >
              <span>
                <span className="flex items-center gap-2 text-sm font-semibold">
                  <input
                    checked={scopeMode === option.value}
                    className="size-4 accent-primary"
                    name="scope"
                    onChange={() => onScopeModeChange(option.value)}
                    type="radio"
                  />
                  {option.label}
                </span>
                <span className="mt-2 block text-sm leading-5 text-[var(--on-surface-variant)]">
                  {option.description}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>

      {scopeMode === "workspaces" ? (
        <div className="space-y-3 rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4">
          <div className="flex items-center justify-between gap-3">
            <Label>Workspaces</Label>
            <Badge variant="outline">{selectedWorkspaceIds.size} selected</Badge>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {activeWorkspaces.map((workspace) => (
              <label
                className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-[var(--outline-variant)] bg-white px-3 text-sm"
                key={workspace.id}
              >
                <input
                  checked={selectedWorkspaceIds.has(workspace.id)}
                  className="size-4 accent-primary"
                  onChange={() => onWorkspaceToggle(workspace.id)}
                  type="checkbox"
                />
                <span className="min-w-0">
                  <span className="block truncate font-medium">
                    {workspaceName(activeWorkspaces, workspace.id)}
                  </span>
                  <span className="block truncate text-xs text-[var(--on-surface-variant)]">
                    {workspace.slug}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {activeWorkspaces.length === 0 ? (
            <p className="text-sm text-[var(--on-surface-variant)]">
              No active workspaces are available.
            </p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
