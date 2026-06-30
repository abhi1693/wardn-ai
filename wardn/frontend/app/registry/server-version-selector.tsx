"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type ServerVersionOption = {
  isDefault: boolean;
  version: string;
};

type ServerVersionSelectorProps = {
  currentVersion: string;
  organizationId: string;
  serverName: string;
  versions: ServerVersionOption[];
};

function encodedServerName(serverName: string) {
  return serverName.split("/").map(encodeURIComponent).join("/");
}

function catalogServerPath(organizationId: string, serverName: string, version: string) {
  return `/org/${encodeURIComponent(organizationId)}/catalog/${encodedServerName(
    serverName
  )}?version=${encodeURIComponent(version)}`;
}

function defaultVersionUrl(serverName: string, version: string) {
  return `/api/mcp/registry/servers/${encodedServerName(serverName)}/${encodeURIComponent(
    version
  )}/default`;
}

export function ServerVersionSelector({
  currentVersion,
  organizationId,
  serverName,
  versions,
}: ServerVersionSelectorProps) {
  const router = useRouter();
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const current = versions.find((version) => version.version === currentVersion);

  async function makeDefault() {
    setIsSaving(true);
    setError("");
    try {
      const response = await fetch(defaultVersionUrl(serverName, currentVersion), {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error("Default version could not be updated.");
      }
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Default version could not be updated.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Versions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <Select
          onValueChange={(version) =>
            router.push(catalogServerPath(organizationId, serverName, version))
          }
          value={currentVersion}
        >
          <SelectTrigger aria-label="Select server version">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {versions.map((version) => (
              <SelectItem key={version.version} value={version.version}>
                <span className="flex items-center gap-2">
                  <span>{version.version}</span>
                  {version.isDefault ? <span className="text-muted-foreground">Default</span> : null}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-3">
          {!current?.isDefault ? (
            <span className="text-muted-foreground">Not the org default</span>
          ) : null}
          <Button
            className="ml-auto"
            disabled={Boolean(current?.isDefault) || isSaving}
            onClick={makeDefault}
            size="sm"
            type="button"
          >
            {isSaving ? <Loader2 className="size-4 animate-spin" /> : null}
            Make default
          </Button>
        </div>

        {error ? <div className="text-xs text-destructive">{error}</div> : null}
      </CardContent>
    </Card>
  );
}
