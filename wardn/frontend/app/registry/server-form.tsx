"use client";

import { ApiError } from "@/lib/api/client";

import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  organizationMcpRegistryCreateServerVersion,
  organizationMcpRegistryImportRepositoryMetadata,
  organizationMcpRegistryUpdateServerVersion,
} from "@/lib/api/generated/organization-mcp-registry/organization-mcp-registry";
import type { MCPServerCreate } from "@/lib/api/generated/model";

import {
  DEFAULT_SCHEMA,
  generatedServerName,
  importedPackages,
  importedRemotes,
  initialPackages,
  initialRemotes,
  installServerUrl,
  publicEnvironment,
  publicHeaders,
  publicPackageArguments,
  records,
  REPOSITORY_SOURCE_OPTIONS,
  SERVER_NAME_PATTERN,
  stringValue,
  type EnvironmentField,
  type HeaderField,
  type PackageArgumentField,
  type PackageTarget,
  type RemoteTarget,
  type ServerFormProps,
  type SourceMetadata,
} from "./server-form-domain";
import { PackageTargetsSection, RemoteEndpointsSection } from "./server-form-sections";

export function ServerForm({
  createSuccessPath,
  editSuccessPath,
  installBasePath,
  initialServer,
  mode,
  organizationId,
}: ServerFormProps) {
  const router = useRouter();
  const initialRepository = initialServer?.repository as Record<string, unknown> | null | undefined;
  const initialIcon = records(initialServer?.icons)[0];
  const [name, setName] = useState(initialServer?.name ?? "");
  const [isNameOverrideEnabled, setIsNameOverrideEnabled] = useState(mode === "edit");
  const [title, setTitle] = useState(initialServer?.title ?? "");
  const [version, setVersion] = useState(initialServer?.version ?? "latest");
  const [description, setDescription] = useState(initialServer?.description ?? "");
  const [websiteUrl, setWebsiteUrl] = useState(initialServer?.websiteUrl ?? "");
  const [repositorySource, setRepositorySource] = useState(stringValue(initialRepository?.source));
  const [repositoryUrl, setRepositoryUrl] = useState(stringValue(initialRepository?.url));
  const [repositorySubfolder, setRepositorySubfolder] = useState(
    stringValue(initialRepository?.subfolder)
  );
  const [iconUrl, setIconUrl] = useState(stringValue(initialIcon?.src));
  const [remotes, setRemotes] = useState<RemoteTarget[]>(() => initialRemotes(initialServer));
  const [packages, setPackages] = useState<PackageTarget[]>(() => initialPackages(initialServer));
  const [error, setError] = useState("");
  const [sourceImportMessage, setSourceImportMessage] = useState("");
  const [isImportingSource, setIsImportingSource] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const derivedName = generatedServerName(repositorySource, repositoryUrl, packages);
  const effectiveName = mode === "create" && !isNameOverrideEnabled ? name || derivedName : name;

  function updateRemote(id: string, patch: Partial<RemoteTarget>) {
    setRemotes((current) =>
      current.map((remote) => (remote.id === id ? { ...remote, ...patch } : remote))
    );
  }

  function updateRemoteHeader(remoteId: string, headerId: string, patch: Partial<HeaderField>) {
    setRemotes((current) =>
      current.map((remote) =>
        remote.id === remoteId
          ? {
              ...remote,
              headers: remote.headers.map((header) =>
                header.id === headerId ? { ...header, ...patch } : header
              ),
            }
          : remote
      )
    );
  }

  function updatePackage(id: string, patch: Partial<PackageTarget>) {
    setPackages((current) =>
      current.map((packageTarget) =>
        packageTarget.id === id ? { ...packageTarget, ...patch } : packageTarget
      )
    );
  }

  function updatePackageEnvironment(
    packageId: string,
    environmentId: string,
    patch: Partial<EnvironmentField>
  ) {
    setPackages((current) =>
      current.map((packageTarget) =>
        packageTarget.id === packageId
          ? {
              ...packageTarget,
              environmentVariables: packageTarget.environmentVariables.map((envVar) =>
                envVar.id === environmentId ? { ...envVar, ...patch } : envVar
              ),
            }
          : packageTarget
      )
    );
  }

  function updatePackageArgument(
    packageId: string,
    argumentId: string,
    patch: Partial<PackageArgumentField>
  ) {
    setPackages((current) =>
      current.map((packageTarget) =>
        packageTarget.id === packageId
          ? {
              ...packageTarget,
              packageArguments: packageTarget.packageArguments.map((argument) =>
                argument.id === argumentId ? { ...argument, ...patch } : argument
              ),
            }
          : packageTarget
      )
    );
  }

  async function importSourceMetadata() {
    setError("");
    setSourceImportMessage("");
    setIsImportingSource(true);

    try {
      const metadata = (await organizationMcpRegistryImportRepositoryMetadata(
        organizationId,
        { repositoryUrl }
      )) as SourceMetadata;
      const metadataRepository = metadata.repository ?? {};
      const metadataPackages = importedPackages(metadata.packages);
      const metadataRemotes = importedRemotes(metadata.remotes);

      setRepositorySource(metadataRepository.source || "github");
      setRepositoryUrl(metadataRepository.url || repositoryUrl);
      setRepositorySubfolder(metadataRepository.subfolder || "");
      setName(metadata.name || "");
      setTitle(metadata.title || "");
      setVersion(metadata.version || "latest");
      setDescription(metadata.description || "");
      setWebsiteUrl(metadata.websiteUrl || metadataRepository.url || repositoryUrl);
      setIconUrl(metadata.iconUrl || "");
      setPackages(metadataPackages);
      setRemotes(metadataRemotes);
      setSourceImportMessage(
        metadata.source === "server.json"
          ? "Catalog document loaded."
          : metadata.source === "mcp.json"
            ? "MCP client configuration loaded."
            : "Repository metadata loaded."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Source metadata could not be loaded.");
    } finally {
      setIsImportingSource(false);
    }
  }

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const serverName = effectiveName.trim();
      if (!serverName) {
        throw new Error("Add repository details or override the server name.");
      }
      if (!SERVER_NAME_PATTERN.test(serverName)) {
        throw new Error("Server name must use the namespace/server format.");
      }

      const remotePayload = remotes
        .filter((remote) => remote.url.trim())
        .map((remote) => ({
          type: remote.type.trim() || "streamable-http",
          url: remote.url.trim(),
          headers: publicHeaders(remote.headers),
        }));
      const packagePayload = packages
        .filter((packageTarget) => packageTarget.identifier.trim())
        .map((packageTarget) => ({
          registryType: packageTarget.registryType.trim() || "npm",
          identifier: packageTarget.identifier.trim(),
          version: packageTarget.version.trim() || version.trim(),
          transport: { type: packageTarget.transportType.trim() || "stdio" },
          environmentVariables: publicEnvironment(packageTarget.environmentVariables),
          packageArguments: publicPackageArguments(packageTarget.packageArguments),
        }));

      if (remotePayload.length === 0 && packagePayload.length === 0) {
        throw new Error("Add at least one remote endpoint or package target.");
      }

      const repository = repositoryUrl.trim()
        ? {
            source: repositorySource.trim() || "github",
            url: repositoryUrl.trim(),
            subfolder: repositorySubfolder.trim(),
          }
        : null;
      const icons = iconUrl.trim()
        ? [
            {
              src: iconUrl.trim(),
              sizes: ["any"],
            },
          ]
        : [];
      const payload = {
        $schema: initialServer?.$schema ?? DEFAULT_SCHEMA,
        name: serverName,
        title: title.trim(),
        description: description.trim(),
        version: version.trim(),
        websiteUrl: websiteUrl.trim(),
        repository,
        remotes: remotePayload,
        packages: packagePayload,
        icons,
      };

      try {
        if (mode === "create") {
          await organizationMcpRegistryCreateServerVersion(
            organizationId,
            payload as MCPServerCreate
          );
        } else {
          await organizationMcpRegistryUpdateServerVersion(
            organizationId,
            initialServer?.name ?? name,
            initialServer?.version ?? version,
            payload as MCPServerCreate
          );
        }
      } catch (caught) {
        if (mode === "create" && caught instanceof ApiError && caught.status === 409) {
          if (createSuccessPath) {
            throw new Error("That server version already exists.");
          }
          router.push(installServerUrl(installBasePath, serverName, version.trim()));
          router.refresh();
          return;
        }
        throw caught;
      }

      router.push(
        mode === "create"
          ? createSuccessPath ?? installServerUrl(installBasePath, serverName, version.trim())
          : editSuccessPath ?? createSuccessPath ?? "/org"
      );
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The server could not be saved.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={submitForm}>
      {error ? (
        <AsyncFeedback variant="error">{error}</AsyncFeedback>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Source</CardTitle>
          <Button
            disabled={!repositoryUrl.trim() || isImportingSource}
            onClick={importSourceMetadata}
            type="button"
            variant="outline"
          >
            {isImportingSource ? "Importing" : "Import"}
          </Button>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="server-repository-source">Repository Source</Label>
            <Select
              onValueChange={(value) => setRepositorySource(value)}
              value={repositorySource}
            >
              <SelectTrigger id="server-repository-source">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {REPOSITORY_SOURCE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="server-repository-url">Repository URL</Label>
            <Input
              id="server-repository-url"
              onChange={(event) => {
                setRepositoryUrl(event.target.value);
                setSourceImportMessage("");
                if (mode === "create" && !isNameOverrideEnabled) {
                  setName("");
                }
              }}
              placeholder="https://github.com/org/repo"
              value={repositoryUrl}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="server-repository-subfolder">Repository Subfolder</Label>
            <Input
              id="server-repository-subfolder"
              onChange={(event) => setRepositorySubfolder(event.target.value)}
              value={repositorySubfolder}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="server-icon-url">Icon URL</Label>
            <Input
              id="server-icon-url"
              onChange={(event) => setIconUrl(event.target.value)}
              placeholder="https://example.com/icon.svg"
              value={iconUrl}
            />
          </div>
          {sourceImportMessage ? (
            <AsyncFeedback className="md:col-span-2" variant="progress">
              {sourceImportMessage}
            </AsyncFeedback>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Server</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="server-name">Name</Label>
              {mode === "create" ? (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    checked={isNameOverrideEnabled}
                    onChange={(event) => {
                      const isEnabled = event.target.checked;
                      setIsNameOverrideEnabled(isEnabled);
                      if (isEnabled && !name.trim()) {
                        setName(derivedName);
                      }
                    }}
                    type="checkbox"
                  />
                  Override
                </label>
              ) : null}
            </div>
            <Input
              disabled={mode === "edit"}
              id="server-name"
              onChange={(event) => setName(event.target.value)}
              placeholder={
                isNameOverrideEnabled ? "io.github.example/server" : "Generated from source"
              }
              readOnly={mode === "create" && !isNameOverrideEnabled}
              required={mode === "edit" || isNameOverrideEnabled}
              value={effectiveName}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="server-version">Version</Label>
            <Input
              disabled={mode === "edit"}
              id="server-version"
              onChange={(event) => setVersion(event.target.value)}
              placeholder="1.0.0"
              required
              value={version}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="server-title">Title</Label>
            <Input
              id="server-title"
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Grafana"
              value={title}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="server-website">Website URL</Label>
            <Input
              id="server-website"
              onChange={(event) => setWebsiteUrl(event.target.value)}
              placeholder="https://example.com"
              value={websiteUrl}
            />
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="server-description">Description</Label>
            <textarea
              className="min-h-80 rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              id="server-description"
              onChange={(event) => setDescription(event.target.value)}
              required
              value={description}
            />
          </div>
        </CardContent>
      </Card>

      <RemoteEndpointsSection
        remotes={remotes}
        setRemotes={setRemotes}
        updateRemote={updateRemote}
        updateRemoteHeader={updateRemoteHeader}
      />

      <PackageTargetsSection
        packages={packages}
        setPackages={setPackages}
        updatePackage={updatePackage}
        updatePackageArgument={updatePackageArgument}
        updatePackageEnvironment={updatePackageEnvironment}
      />

      <div className="flex justify-end gap-2">
        <Button
          disabled={isSubmitting}
          onClick={() => router.push(editSuccessPath ?? createSuccessPath ?? "/org")}
          type="button"
          variant="outline"
        >
          Cancel
        </Button>
        <Button disabled={isSubmitting} type="submit">
          <Save className="size-4" />
          {isSubmitting ? "Saving" : "Save"}
        </Button>
      </div>
    </form>
  );
}
