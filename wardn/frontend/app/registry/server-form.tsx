"use client";

import { Plus, Save, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { MCPServerDocument } from "@/lib/api/generated/model";

const DEFAULT_SCHEMA =
  "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json";
const SERVER_NAME_PATTERN = /^[a-zA-Z0-9.-]+\/[a-zA-Z0-9._-]+$/;

let generatedId = 0;

type ServerFormProps = {
  createSuccessPath?: string;
  editSuccessPath?: string;
  installBasePath: string;
  initialServer?: MCPServerDocument;
  mode: "create" | "edit";
};

type HeaderField = {
  id: string;
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
};

type EnvironmentField = HeaderField & {
  defaultValue: string;
  format: string;
};

type PackageArgumentField = HeaderField & {
  defaultValue: string;
  flag: string;
  format: string;
  options: string;
  value: string;
};

type RemoteTarget = {
  id: string;
  type: string;
  url: string;
  headers: HeaderField[];
};

type PackageTarget = {
  id: string;
  registryType: string;
  identifier: string;
  version: string;
  transportType: string;
  environmentVariables: EnvironmentField[];
  packageArguments: PackageArgumentField[];
};

type SourceMetadata = {
  source?: string;
  name?: string;
  title?: string;
  description?: string;
  version?: string;
  websiteUrl?: string;
  repository?: {
    source?: string;
    url?: string;
    subfolder?: string;
  };
  iconUrl?: string;
  remotes?: unknown;
  packages?: unknown;
};

const PACKAGE_RUNTIME_OPTIONS = [
  { value: "uvx", label: "UVX package" },
  { value: "npm", label: "NPM package" },
  { value: "pypi", label: "PyPI package" },
  { value: "oci", label: "OCI image" },
];

const REPOSITORY_SOURCE_OPTIONS = [
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "bitbucket", label: "Bitbucket" },
  { value: "git", label: "Git" },
];

const PACKAGE_ARGUMENT_FORMAT_OPTIONS = [
  { value: "string", label: "Text" },
  { value: "boolean", label: "Toggle" },
  { value: "integer", label: "Number" },
  { value: "select", label: "Select" },
  { value: "file", label: "File" },
];

function createId(prefix: string) {
  generatedId += 1;
  return `${prefix}-${generatedId}`;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function booleanValue(value: unknown) {
  return value === true;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

function initialHeaders(value: unknown): HeaderField[] {
  return records(value).map((header) => ({
    id: createId("header"),
    name: stringValue(header.name),
    description: stringValue(header.description),
    required: booleanValue(header.isRequired),
    secret: booleanValue(header.isSecret),
  }));
}

function initialEnvironment(value: unknown): EnvironmentField[] {
  return records(value).map((envVar) => ({
    id: createId("env"),
    name: stringValue(envVar.name),
    description: stringValue(envVar.description),
    defaultValue: stringValue(envVar.default),
    format: stringValue(envVar.format) || "string",
    required: booleanValue(envVar.isRequired),
    secret: booleanValue(envVar.isSecret),
  }));
}

function initialPackageArguments(value: unknown): PackageArgumentField[] {
  return records(value).map((argument) => ({
    id: createId("arg"),
    name: stringValue(argument.name),
    description: stringValue(argument.description),
    defaultValue: stringValue(argument.default),
    flag: stringValue(argument.flag),
    format: stringValue(argument.format) || "string",
    options: Array.isArray(argument.options) ? argument.options.map(String).join(", ") : "",
    required: booleanValue(argument.isRequired),
    secret: booleanValue(argument.isSecret),
    value: stringValue(argument.value),
  }));
}

function initialRemotes(server?: MCPServerDocument): RemoteTarget[] {
  return records(server?.remotes).map((remote) => ({
    id: createId("remote"),
    type: stringValue(remote.type) || "streamable-http",
    url: stringValue(remote.url),
    headers: initialHeaders(remote.headers),
  }));
}

function initialPackages(server?: MCPServerDocument): PackageTarget[] {
  return records(server?.packages).map((packageTarget) => {
    const transport = packageTarget.transport as Record<string, unknown> | undefined;
    return {
      id: createId("package"),
      registryType: stringValue(packageTarget.registryType) || "npm",
      identifier: stringValue(packageTarget.identifier),
      version: stringValue(packageTarget.version),
      transportType: stringValue(transport?.type) || "stdio",
      environmentVariables: initialEnvironment(packageTarget.environmentVariables),
      packageArguments: initialPackageArguments(packageTarget.packageArguments),
    };
  });
}

function replaceVersionToken(value: string) {
  return value.replaceAll("$VERSION", "latest");
}

function importedRemotes(value: unknown): RemoteTarget[] {
  return records(value).map((remote) => ({
    id: createId("remote"),
    type: stringValue(remote.type) || "streamable-http",
    url: stringValue(remote.url),
    headers: initialHeaders(remote.headers),
  }));
}

function importedPackages(value: unknown): PackageTarget[] {
  return records(value).map((packageTarget) => {
    const transport = packageTarget.transport as Record<string, unknown> | undefined;
    return {
      id: createId("package"),
      registryType: stringValue(packageTarget.registryType) || "npm",
      identifier: replaceVersionToken(stringValue(packageTarget.identifier)),
      version: replaceVersionToken(stringValue(packageTarget.version)),
      transportType: stringValue(transport?.type) || "stdio",
      environmentVariables: initialEnvironment(packageTarget.environmentVariables),
      packageArguments: initialPackageArguments(packageTarget.packageArguments),
    };
  });
}

function emptyHeader(): HeaderField {
  return {
    id: createId("header"),
    name: "",
    description: "",
    required: false,
    secret: false,
  };
}

function emptyEnvironment(): EnvironmentField {
  return {
    ...emptyHeader(),
    id: createId("env"),
    defaultValue: "",
    format: "string",
  };
}

function emptyPackageArgument(): PackageArgumentField {
  return {
    ...emptyHeader(),
    id: createId("arg"),
    defaultValue: "",
    flag: "",
    format: "string",
    options: "",
    value: "",
  };
}

function emptyRemote(): RemoteTarget {
  return {
    id: createId("remote"),
    type: "streamable-http",
    url: "",
    headers: [],
  };
}

function emptyPackage(): PackageTarget {
  return {
    id: createId("package"),
    registryType: "npm",
    identifier: "",
    version: "",
    transportType: "stdio",
    environmentVariables: [],
    packageArguments: [],
  };
}

function cleanNamespacePart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9.-]+/g, "-")
    .replace(/^[.-]+|[.-]+$/g, "");
}

function cleanNamePart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "");
}

function parseRepositoryUrl(value: string) {
  const rawValue = value.trim();
  if (!rawValue) {
    return null;
  }

  try {
    const url = new URL(rawValue.includes("://") ? rawValue : `https://${rawValue}`);
    const pathParts = url.pathname.split("/").filter(Boolean);
    if (pathParts.length < 2) {
      return null;
    }

    return {
      host: url.hostname.toLowerCase().replace(/^www\./, ""),
      owner: pathParts[0],
      repo: pathParts[1],
    };
  } catch {
    return null;
  }
}

function repositoryNamespace(source: string, host: string, owner: string) {
  const sourceName = source.trim().toLowerCase();
  const ownerPart = cleanNamespacePart(owner);

  if (sourceName === "github" || host === "github.com") {
    return ownerPart ? `io.github.${ownerPart}` : "";
  }
  if (sourceName === "gitlab" || host === "gitlab.com") {
    return ownerPart ? `com.gitlab.${ownerPart}` : "";
  }
  if (sourceName === "bitbucket" || host === "bitbucket.org") {
    return ownerPart ? `org.bitbucket.${ownerPart}` : "";
  }

  const hostNamespace = host
    .split(".")
    .reverse()
    .map(cleanNamespacePart)
    .filter(Boolean)
    .join(".");

  return [hostNamespace, ownerPart].filter(Boolean).join(".");
}

function packageNamespace(registryType: string, identifier: string) {
  const runtime = cleanNamespacePart(registryType || "package");
  const trimmedIdentifier = identifier.trim();
  const scopedMatch = trimmedIdentifier.match(/^@([^/]+)\/(.+)$/);

  if (scopedMatch) {
    return {
      namespace: ["io", runtime, cleanNamespacePart(scopedMatch[1])].filter(Boolean).join("."),
      name: cleanNamePart(scopedMatch[2]),
    };
  }

  return {
    namespace: ["io", runtime].filter(Boolean).join("."),
    name: cleanNamePart(trimmedIdentifier),
  };
}

function generatedServerName(
  repositorySource: string,
  repositoryUrl: string,
  packages: PackageTarget[]
) {
  const repository = parseRepositoryUrl(repositoryUrl);
  if (repository) {
    const namespace = repositoryNamespace(repositorySource, repository.host, repository.owner);
    const serverName = cleanNamePart(repository.repo);
    if (namespace && serverName) {
      return `${namespace}/${serverName}`;
    }
  }

  const packageTarget = packages.find((item) => item.identifier.trim());
  if (packageTarget) {
    const generatedPackage = packageNamespace(
      packageTarget.registryType,
      packageTarget.identifier
    );
    if (generatedPackage.namespace && generatedPackage.name) {
      return `${generatedPackage.namespace}/${generatedPackage.name}`;
    }
  }

  return "";
}

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function responseErrorDetail(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || "";
  } catch {
    return "";
  }
}

function serverVersionUrl(serverName: string, version: string) {
  return `/api/mcp/registry/servers/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}/${encodeURIComponent(version)}`;
}

function installServerUrl(basePath: string, serverName: string, version: string) {
  const params = new URLSearchParams({
    serverName,
    version,
  });
  return `${basePath}/new?${params.toString()}`;
}

function publicHeaders(headers: HeaderField[]) {
  return headers
    .filter((header) => header.name.trim())
    .map((header) => ({
      name: header.name.trim(),
      description: header.description.trim(),
      isRequired: header.required,
      isSecret: header.secret,
    }));
}

function publicEnvironment(environmentVariables: EnvironmentField[]) {
  return environmentVariables
    .filter((envVar) => envVar.name.trim())
    .map((envVar) => ({
      name: envVar.name.trim(),
      description: envVar.description.trim(),
      default: envVar.defaultValue.trim(),
      isRequired: envVar.required,
      isSecret: envVar.secret,
      format: envVar.format || "string",
    }));
}

function publicPackageArguments(packageArguments: PackageArgumentField[]): Record<string, unknown>[] {
  return packageArguments
    .map((argument): Record<string, unknown> | null => {
      const name = argument.name.trim();
      const value = argument.value.trim();
      const description = argument.description.trim();
      if (!name && value) {
        return {
          value,
          description,
        };
      }
      if (!name) {
        return null;
      }
      const options = argument.options
        .split(",")
        .map((option) => option.trim())
        .filter(Boolean);
      return {
        name,
        flag: argument.flag.trim(),
        description,
        default: argument.defaultValue.trim(),
        format: argument.format || "string",
        options,
        isRequired: argument.required,
        isSecret: argument.secret,
      };
    })
    .filter((argument): argument is Record<string, unknown> => Boolean(argument));
}

export function ServerForm({
  createSuccessPath,
  editSuccessPath,
  installBasePath,
  initialServer,
  mode,
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
      const response = await fetch("/api/mcp/registry/source-metadata", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({ repositoryUrl }),
      });

      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Source metadata could not be loaded."));
      }

      const metadata = (await response.json()) as SourceMetadata;
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

      const response = await fetch(
        mode === "create"
          ? "/api/mcp/registry/servers"
          : serverVersionUrl(initialServer?.name ?? name, initialServer?.version ?? version),
        {
          method: mode === "create" ? "POST" : "PUT",
          headers: {
            "content-type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        const detail = await responseErrorDetail(response);
        if (
          mode === "create" &&
          response.status === 409 &&
          detail === "server version already exists"
        ) {
          if (createSuccessPath) {
            throw new Error("That server version already exists.");
          }
          router.push(installServerUrl(installBasePath, serverName, version.trim()));
          router.refresh();
          return;
        }

        throw new Error(
          detail || (mode === "create" ? "Failed to add server." : "Failed to update server.")
        );
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
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
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
            <div className="md:col-span-2 rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              {sourceImportMessage}
            </div>
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

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Remote Endpoints</CardTitle>
          <Button onClick={() => setRemotes((current) => [...current, emptyRemote()])} type="button" variant="outline">
            <Plus className="size-4" />
            Add remote
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {remotes.map((remote, index) => (
            <div className="space-y-4 rounded-md border p-4" key={remote.id}>
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">Remote {index + 1}</div>
                <Button
                  onClick={() => setRemotes((current) => current.filter((item) => item.id !== remote.id))}
                  size="icon"
                  type="button"
                  variant="outline"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <div className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor={`${remote.id}-url`}>URL</Label>
                  <Input
                    id={`${remote.id}-url`}
                    onChange={(event) => updateRemote(remote.id, { url: event.target.value })}
                    placeholder="https://example.com/mcp"
                    value={remote.url}
                  />
                </div>
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">Headers</div>
                  <Button
                    onClick={() =>
                      updateRemote(remote.id, { headers: [...remote.headers, emptyHeader()] })
                    }
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Plus className="size-4" />
                    Add header
                  </Button>
                </div>
                {remote.headers.map((header) => (
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_auto_auto_auto]" key={header.id}>
                    <Input
                      onChange={(event) =>
                        updateRemoteHeader(remote.id, header.id, { name: event.target.value })
                      }
                      placeholder="Header name"
                      value={header.name}
                    />
                    <Input
                      onChange={(event) =>
                        updateRemoteHeader(remote.id, header.id, { description: event.target.value })
                      }
                      placeholder="Description"
                      value={header.description}
                    />
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={header.required}
                        onChange={(event) =>
                          updateRemoteHeader(remote.id, header.id, { required: event.target.checked })
                        }
                        type="checkbox"
                      />
                      Required
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={header.secret}
                        onChange={(event) =>
                          updateRemoteHeader(remote.id, header.id, { secret: event.target.checked })
                        }
                        type="checkbox"
                      />
                      Secret
                    </label>
                    <Button
                      onClick={() =>
                        updateRemote(remote.id, {
                          headers: remote.headers.filter((item) => item.id !== header.id),
                        })
                      }
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Package Targets</CardTitle>
          <Button onClick={() => setPackages((current) => [...current, emptyPackage()])} type="button" variant="outline">
            <Plus className="size-4" />
            Add package
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {packages.map((packageTarget, index) => (
            <div className="space-y-4 rounded-md border p-4" key={packageTarget.id}>
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">Package {index + 1}</div>
                <Button
                  onClick={() =>
                    setPackages((current) => current.filter((item) => item.id !== packageTarget.id))
                  }
                  size="icon"
                  type="button"
                  variant="outline"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)_160px]">
                <div className="grid gap-2">
                  <Label htmlFor={`${packageTarget.id}-registry`}>Runtime</Label>
                  <Select
                    onValueChange={(value) =>
                      updatePackage(packageTarget.id, { registryType: value })
                    }
                    value={packageTarget.registryType}
                  >
                    <SelectTrigger id={`${packageTarget.id}-registry`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PACKAGE_RUNTIME_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor={`${packageTarget.id}-identifier`}>Package</Label>
                  <Input
                    id={`${packageTarget.id}-identifier`}
                    onChange={(event) =>
                      updatePackage(packageTarget.id, { identifier: event.target.value })
                    }
                    placeholder="@scope/package"
                    value={packageTarget.identifier}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor={`${packageTarget.id}-version`}>Version</Label>
                  <Input
                    id={`${packageTarget.id}-version`}
                    onChange={(event) =>
                      updatePackage(packageTarget.id, { version: event.target.value })
                    }
                    value={packageTarget.version}
                  />
                </div>
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">Environment Variables</div>
                  <Button
                    onClick={() =>
                      updatePackage(packageTarget.id, {
                        environmentVariables: [
                          ...packageTarget.environmentVariables,
                          emptyEnvironment(),
                        ],
                      })
                    }
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Plus className="size-4" />
                    Add variable
                  </Button>
                </div>
                {packageTarget.environmentVariables.map((envVar) => (
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)_140px_auto_auto_auto]" key={envVar.id}>
                    <Input
                      onChange={(event) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          name: event.target.value,
                        })
                      }
                      placeholder="Variable name"
                      value={envVar.name}
                    />
                    <Input
                      onChange={(event) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          description: event.target.value,
                        })
                      }
                      placeholder="Description"
                      value={envVar.description}
                    />
                    <Input
                      onChange={(event) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          defaultValue: event.target.value,
                        })
                      }
                      placeholder="Default"
                      value={envVar.defaultValue}
                    />
                    <Select
                      onValueChange={(value) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          format: value,
                        })
                      }
                      value={envVar.format}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PACKAGE_ARGUMENT_FORMAT_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={envVar.required}
                        onChange={(event) =>
                          updatePackageEnvironment(packageTarget.id, envVar.id, {
                            required: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      Required
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={envVar.secret}
                        onChange={(event) =>
                          updatePackageEnvironment(packageTarget.id, envVar.id, {
                            secret: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      Secret
                    </label>
                    <Button
                      onClick={() =>
                        updatePackage(packageTarget.id, {
                          environmentVariables: packageTarget.environmentVariables.filter(
                            (item) => item.id !== envVar.id
                          ),
                        })
                      }
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                ))}
              </div>
              <div className="space-y-3 border-t pt-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">Runtime Arguments</div>
                    <div className="text-xs text-muted-foreground">
                      Define static process arguments or user-configurable flags shown during installation.
                    </div>
                  </div>
                  <Button
                    onClick={() =>
                      updatePackage(packageTarget.id, {
                        packageArguments: [
                          ...packageTarget.packageArguments,
                          emptyPackageArgument(),
                        ],
                      })
                    }
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Plus className="size-4" />
                    Add argument
                  </Button>
                </div>
                {packageTarget.packageArguments.map((argument) => (
                  <div className="space-y-3 rounded-md border p-3" key={argument.id}>
                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_140px_auto]">
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            name: event.target.value,
                          })
                        }
                        placeholder="Config key, e.g. SERVER_LOG_LEVEL"
                        value={argument.name}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            flag: event.target.value,
                          })
                        }
                        placeholder="Flag, e.g. --log-level"
                        value={argument.flag}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            value: event.target.value,
                          })
                        }
                        placeholder="Static value, e.g. stdio"
                        value={argument.value}
                      />
                      <Select
                        onValueChange={(value) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            format: value,
                          })
                        }
                        value={argument.format}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PACKAGE_ARGUMENT_FORMAT_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        onClick={() =>
                          updatePackage(packageTarget.id, {
                            packageArguments: packageTarget.packageArguments.filter(
                              (item) => item.id !== argument.id
                            ),
                          })
                        }
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                    <div className="grid gap-3 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            description: event.target.value,
                          })
                        }
                        placeholder="Description"
                        value={argument.description}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            defaultValue: event.target.value,
                          })
                        }
                        placeholder="Default"
                        value={argument.defaultValue}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            options: event.target.value,
                          })
                        }
                        placeholder="Options, comma-separated"
                        value={argument.options}
                      />
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          checked={argument.required}
                          onChange={(event) =>
                            updatePackageArgument(packageTarget.id, argument.id, {
                              required: event.target.checked,
                            })
                          }
                          type="checkbox"
                        />
                        Required
                      </label>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          checked={argument.secret}
                          onChange={(event) =>
                            updatePackageArgument(packageTarget.id, argument.id, {
                              secret: event.target.checked,
                            })
                          }
                          type="checkbox"
                        />
                        Secret
                      </label>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

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
