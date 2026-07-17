import type { MCPServerDocument } from "@/lib/api/generated/model";

export const DEFAULT_SCHEMA =
  "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json";
export const SERVER_NAME_PATTERN = /^[a-zA-Z0-9.-]+\/[a-zA-Z0-9._-]+$/;

let generatedId = 0;

export type ServerFormProps = {
  createSuccessPath?: string;
  editSuccessPath?: string;
  installBasePath: string;
  initialServer?: MCPServerDocument;
  mode: "create" | "edit";
  organizationId: string;
};

export type HeaderField = {
  id: string;
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
};

export type EnvironmentField = HeaderField & {
  defaultValue: string;
  format: string;
};

export type PackageArgumentField = HeaderField & {
  defaultValue: string;
  flag: string;
  format: string;
  options: string;
  value: string;
};

export type RemoteTarget = {
  id: string;
  type: string;
  url: string;
  headers: HeaderField[];
};

export type PackageTarget = {
  id: string;
  registryType: string;
  identifier: string;
  version: string;
  transportType: string;
  environmentVariables: EnvironmentField[];
  packageArguments: PackageArgumentField[];
};

export type SourceMetadata = {
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

export const PACKAGE_RUNTIME_OPTIONS = [
  { value: "uvx", label: "UVX package" },
  { value: "npm", label: "NPM package" },
  { value: "pypi", label: "PyPI package" },
  { value: "oci", label: "OCI image" },
];

export const REPOSITORY_SOURCE_OPTIONS = [
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "bitbucket", label: "Bitbucket" },
  { value: "git", label: "Git" },
];

export const PACKAGE_ARGUMENT_FORMAT_OPTIONS = [
  { value: "string", label: "Text" },
  { value: "boolean", label: "Toggle" },
  { value: "integer", label: "Number" },
  { value: "select", label: "Select" },
  { value: "file", label: "File" },
];

export function createId(prefix: string) {
  generatedId += 1;
  return `${prefix}-${generatedId}`;
}

export function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

export function booleanValue(value: unknown) {
  return value === true;
}

export function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

export function initialHeaders(value: unknown): HeaderField[] {
  return records(value).map((header) => ({
    id: createId("header"),
    name: stringValue(header.name),
    description: stringValue(header.description),
    required: booleanValue(header.isRequired),
    secret: booleanValue(header.isSecret),
  }));
}

export function initialEnvironment(value: unknown): EnvironmentField[] {
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

export function initialPackageArguments(value: unknown): PackageArgumentField[] {
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

export function initialRemotes(server?: MCPServerDocument): RemoteTarget[] {
  return records(server?.remotes).map((remote) => ({
    id: createId("remote"),
    type: stringValue(remote.type) || "streamable-http",
    url: stringValue(remote.url),
    headers: initialHeaders(remote.headers),
  }));
}

export function initialPackages(server?: MCPServerDocument): PackageTarget[] {
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

export function replaceVersionToken(value: string) {
  return value.replaceAll("$VERSION", "latest");
}

export function importedRemotes(value: unknown): RemoteTarget[] {
  return records(value).map((remote) => ({
    id: createId("remote"),
    type: stringValue(remote.type) || "streamable-http",
    url: stringValue(remote.url),
    headers: initialHeaders(remote.headers),
  }));
}

export function importedPackages(value: unknown): PackageTarget[] {
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

export function emptyHeader(): HeaderField {
  return {
    id: createId("header"),
    name: "",
    description: "",
    required: false,
    secret: false,
  };
}

export function emptyEnvironment(): EnvironmentField {
  return {
    ...emptyHeader(),
    id: createId("env"),
    defaultValue: "",
    format: "string",
  };
}

export function emptyPackageArgument(): PackageArgumentField {
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

export function emptyRemote(): RemoteTarget {
  return {
    id: createId("remote"),
    type: "streamable-http",
    url: "",
    headers: [],
  };
}

export function emptyPackage(): PackageTarget {
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

export function cleanNamespacePart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9.-]+/g, "-")
    .replace(/^[.-]+|[.-]+$/g, "");
}

export function cleanNamePart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "");
}

export function parseRepositoryUrl(value: string) {
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

export function repositoryNamespace(source: string, host: string, owner: string) {
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

export function packageNamespace(registryType: string, identifier: string) {
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

export function generatedServerName(
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

export function installServerUrl(basePath: string, serverName: string, version: string) {
  const params = new URLSearchParams({
    serverName,
    version,
  });
  return `${basePath}/new?${params.toString()}`;
}

export function publicHeaders(headers: HeaderField[]) {
  return headers
    .filter((header) => header.name.trim())
    .map((header) => ({
      name: header.name.trim(),
      description: header.description.trim(),
      isRequired: header.required,
      isSecret: header.secret,
    }));
}

export function publicEnvironment(environmentVariables: EnvironmentField[]) {
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

export function publicPackageArguments(packageArguments: PackageArgumentField[]): Record<string, unknown>[] {
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

