import { NextRequest, NextResponse } from "next/server";

type GitHubRepository = {
  default_branch?: string;
  description?: string | null;
  full_name?: string;
  homepage?: string | null;
  html_url?: string;
  name?: string;
};

type GitHubContent = {
  content?: string;
  encoding?: string;
  type?: string;
};

type GitHubRelease = {
  tag_name?: string;
};

type ServerDocument = {
  $schema?: string;
  name?: string;
  title?: string;
  description?: string;
  repository?: {
    source?: string;
    url?: string;
    subfolder?: string;
  };
  version?: string;
  websiteUrl?: string;
  icon?: string;
  icons?: Array<{ src?: string }>;
  packages?: unknown[];
  remotes?: unknown[];
};

function parseGitHubRepositoryUrl(value: string) {
  try {
    const url = new URL(value.includes("://") ? value : `https://${value}`);
    if (url.hostname.toLowerCase().replace(/^www\./, "") !== "github.com") {
      return null;
    }

    const [owner, rawRepo] = url.pathname.split("/").filter(Boolean);
    if (!owner || !rawRepo) {
      return null;
    }

    return {
      owner,
      repo: rawRepo.replace(/\.git$/i, ""),
    };
  } catch {
    return null;
  }
}

function titleFromRepositoryName(value: string) {
  return value
    .replace(/[-_]+/g, " ")
    .replace(/\bmcp\b/gi, "MCP")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function githubHeaders() {
  const headers: Record<string, string> = {
    accept: "application/vnd.github+json",
    "user-agent": "wardn-ai",
  };

  if (process.env.GITHUB_TOKEN) {
    headers.authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  }

  return headers;
}

async function fetchGitHubJson<T>(url: string) {
  const response = await fetch(url, {
    headers: githubHeaders(),
    next: { revalidate: 300 },
  });

  if (!response.ok) {
    return null;
  }

  return (await response.json()) as T;
}

async function fetchRepositoryFile(owner: string, repo: string, path: string, branch: string) {
  const file = await fetchGitHubJson<GitHubContent>(
    `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(
      repo
    )}/contents/${path}?ref=${encodeURIComponent(branch)}`
  );

  if (file?.type !== "file" || file.encoding !== "base64" || !file.content) {
    return "";
  }

  return Buffer.from(file.content, "base64").toString("utf8");
}

async function fetchRepositoryReadme(owner: string, repo: string, branch: string) {
  const file = await fetchGitHubJson<GitHubContent>(
    `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(
      repo
    )}/readme?ref=${encodeURIComponent(branch)}`
  );

  if (file?.type !== "file" || file.encoding !== "base64" || !file.content) {
    return "";
  }

  return Buffer.from(file.content, "base64").toString("utf8");
}

async function fetchLatestReleaseVersion(owner: string, repo: string) {
  const release = await fetchGitHubJson<GitHubRelease>(
    `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(
      repo
    )}/releases/latest`
  );
  const tagName = release?.tag_name?.trim() || "";

  return tagName.replace(/^v(?=\d)/i, "");
}

function replaceVersionTokens<T>(value: T, version: string): T {
  const replacement = version || "latest";

  if (typeof value === "string") {
    return value.replaceAll("$VERSION", replacement) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => replaceVersionTokens(item, replacement)) as T;
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, replaceVersionTokens(item, replacement)])
    ) as T;
  }

  return value;
}

function normalizedVersion(value: unknown, releaseVersion: string) {
  const version = typeof value === "string" ? value.trim() : "";
  if (!version) {
    return releaseVersion || "latest";
  }

  return replaceVersionTokens(version, releaseVersion);
}

function rawGitHubUrl(owner: string, repo: string, branch: string, path: string) {
  return `https://raw.githubusercontent.com/${encodeURIComponent(owner)}/${encodeURIComponent(
    repo
  )}/${encodeURIComponent(branch)}/${path
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/")}`;
}

function normalizeIconUrl(
  icon: unknown,
  icons: ServerDocument["icons"],
  owner: string,
  repo: string,
  branch: string
) {
  const iconPath =
    typeof icon === "string" && icon.trim()
      ? icon.trim()
      : icons?.find((item) => typeof item.src === "string" && item.src.trim())?.src?.trim() || "";

  if (!iconPath) {
    return "";
  }

  if (/^https?:\/\//i.test(iconPath)) {
    return iconPath;
  }

  return rawGitHubUrl(owner, repo, branch, iconPath.replace(/^\/+/, ""));
}

function normalizeServerJson(
  rawServerJson: string,
  readme: string,
  releaseVersion: string,
  owner: string,
  repo: string,
  branch: string,
  canonicalRepositoryUrl: string
) {
  if (!rawServerJson) {
    return null;
  }

  try {
    const document = JSON.parse(rawServerJson) as ServerDocument;
    if (!document.name || !document.description) {
      return null;
    }

    const version = normalizedVersion(document.version, releaseVersion);

    return {
      source: "server.json",
      name: document.name,
      title: document.title || titleFromRepositoryName(repo),
      description: readme || document.description,
      version,
      websiteUrl: document.websiteUrl || canonicalRepositoryUrl,
      repository: {
        source: document.repository?.source || "github",
        url: document.repository?.url || canonicalRepositoryUrl,
        subfolder: document.repository?.subfolder || "",
      },
      iconUrl: normalizeIconUrl(document.icon, document.icons, owner, repo, branch),
      remotes: Array.isArray(document.remotes) ? replaceVersionTokens(document.remotes, version) : [],
      packages: Array.isArray(document.packages) ? replaceVersionTokens(document.packages, version) : [],
    };
  } catch {
    return null;
  }
}

function packageFromPackageJson(rawPackageJson: string, releaseVersion: string) {
  if (!rawPackageJson) {
    return null;
  }

  try {
    const packageJson = JSON.parse(rawPackageJson) as { name?: unknown; version?: unknown };
    if (typeof packageJson.name !== "string" || !packageJson.name.trim()) {
      return null;
    }

    return {
      registryType: "npm",
      identifier: packageJson.name.trim(),
      version:
        releaseVersion || (typeof packageJson.version === "string" ? packageJson.version.trim() : ""),
    };
  } catch {
    return null;
  }
}

function projectSectionValue(section: string, key: string) {
  const match = section.match(new RegExp(`^${key}\\s*=\\s*["']([^"']+)["']`, "m"));
  return match?.[1]?.trim() || "";
}

function tomlSection(rawToml: string, sectionName: string) {
  const escapedSectionName = sectionName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return (
    rawToml.match(new RegExp(`^\\[${escapedSectionName}\\]\\s*\\n([\\s\\S]*?)(?=^\\[|\\s*$)`, "m"))
      ?.[1] || ""
  );
}

function packageFromPyproject(rawPyproject: string, releaseVersion: string) {
  if (!rawPyproject) {
    return null;
  }

  const projectSection = tomlSection(rawPyproject, "project");
  const poetrySection = tomlSection(rawPyproject, "tool.poetry");
  const name = projectSectionValue(projectSection, "name") || projectSectionValue(poetrySection, "name");
  if (!name) {
    return null;
  }

  return {
    registryType: "uvx",
    identifier: name,
    version: releaseVersion,
  };
}

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => null)) as { repositoryUrl?: unknown } | null;
  const repositoryUrl = typeof body?.repositoryUrl === "string" ? body.repositoryUrl.trim() : "";
  const repository = parseGitHubRepositoryUrl(repositoryUrl);

  if (!repository) {
    return NextResponse.json(
      { detail: "Enter a GitHub repository URL." },
      { status: 400 }
    );
  }

  const githubRepository = await fetchGitHubJson<GitHubRepository>(
    `https://api.github.com/repos/${encodeURIComponent(repository.owner)}/${encodeURIComponent(
      repository.repo
    )}`
  );

  if (!githubRepository) {
    return NextResponse.json(
      { detail: "Repository metadata could not be loaded." },
      { status: 404 }
    );
  }

  const branch = githubRepository.default_branch || "main";
  const [serverJson, readme, packageJson, pyproject, releaseVersion] = await Promise.all([
    fetchRepositoryFile(repository.owner, repository.repo, "server.json", branch),
    fetchRepositoryReadme(repository.owner, repository.repo, branch),
    fetchRepositoryFile(repository.owner, repository.repo, "package.json", branch),
    fetchRepositoryFile(repository.owner, repository.repo, "pyproject.toml", branch),
    fetchLatestReleaseVersion(repository.owner, repository.repo),
  ]);
  const canonicalRepositoryUrl =
    githubRepository.html_url || `https://github.com/${repository.owner}/${repository.repo}`;
  const repositoryName = githubRepository.name || repository.repo;
  const serverDocument = normalizeServerJson(
    serverJson,
    readme,
    releaseVersion,
    repository.owner,
    repository.repo,
    branch,
    canonicalRepositoryUrl
  );

  if (serverDocument) {
    return NextResponse.json(serverDocument);
  }

  const packages = [
    packageFromPackageJson(packageJson, releaseVersion),
    packageFromPyproject(pyproject, releaseVersion),
  ].filter(
    (item): item is { registryType: string; identifier: string; version: string } => Boolean(item)
  );

  return NextResponse.json({
    source: "repository",
    title: titleFromRepositoryName(repositoryName),
    description: readme || githubRepository.description || "",
    version: releaseVersion || "latest",
    websiteUrl: githubRepository.homepage || canonicalRepositoryUrl,
    repository: {
      source: "github",
      url: canonicalRepositoryUrl,
      subfolder: "",
    },
    packages,
  });
}
