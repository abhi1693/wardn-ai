import {
  ExternalLink,
  GitBranch,
  Globe,
  KeyRound,
  Network,
  Package,
  Pencil,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/app/components/app-shell";
import { ServerVersionSelector } from "@/app/registry/server-version-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  MCPRegistryServerResponse,
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  getWorkspaceContext,
  organizationMcpRegistryPath,
  type WorkspaceContext,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";

type RegistryServerPageProps = {
  params: Promise<{
    organizationId: string;
    serverName: string[];
  }>;
  searchParams: Promise<{
    version?: string;
  }>;
};

type LinkTarget = {
  label: string;
  url: string;
};

type MarkdownBlock =
  | { type: "blockquote"; lines: string[] }
  | { type: "code"; code: string }
  | { type: "heading"; level: number; text: string }
  | { type: "hr" }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "paragraph"; text: string };

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function repository(entry: MCPRegistryServerResponse) {
  return entry.server.repository as Record<string, unknown> | null | undefined;
}

function runtimeDisplayName(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === "uvx") {
    return "UVX";
  }
  if (normalized === "npm") {
    return "NPM";
  }
  if (normalized === "pypi") {
    return "PyPI";
  }
  if (normalized === "oci") {
    return "OCI";
  }
  if (normalized === "streamable-http") {
    return "Streamable HTTP";
  }
  if (normalized === "sse") {
    return "SSE";
  }
  return value || "Package";
}

function publisherMeta(entry: MCPRegistryServerResponse) {
  const meta = entry.server._meta as Record<string, unknown> | null | undefined;
  return meta?.["io.modelcontextprotocol.registry/publisher-provided"] as
    | Record<string, unknown>
    | undefined;
}

function sourceLinks(entry: MCPRegistryServerResponse): LinkTarget[] {
  const links: LinkTarget[] = [];
  const websiteUrl = entry.server.websiteUrl;
  const repoUrl = stringValue(repository(entry)?.url);
  const publisher = publisherMeta(entry);
  const docsUrl = stringValue(publisher?.docs);
  const connectUrl = stringValue(publisher?.connect);

  if (websiteUrl) {
    links.push({ label: "Website", url: websiteUrl });
  }
  if (repoUrl && repoUrl !== websiteUrl) {
    links.push({ label: "Repository", url: repoUrl });
  }
  if (docsUrl && docsUrl !== websiteUrl && docsUrl !== repoUrl) {
    links.push({ label: "Docs", url: docsUrl });
  }
  if (connectUrl && connectUrl !== websiteUrl && connectUrl !== repoUrl && connectUrl !== docsUrl) {
    links.push({ label: "Connect", url: connectUrl });
  }

  return links;
}

function schemaInputs(entry: MCPRegistryServerResponse) {
  const headers = (entry.server.remotes ?? []).flatMap((remote) => {
    const value = (remote as Record<string, unknown>).headers;
    return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  });
  const environmentVariables = (entry.server.packages ?? []).flatMap((packageDefinition) => {
    const value = (packageDefinition as Record<string, unknown>).environmentVariables;
    return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  });
  const packageArguments = (entry.server.packages ?? []).flatMap((packageDefinition) => {
    const value = (packageDefinition as Record<string, unknown>).packageArguments;
    return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  });

  return { environmentVariables, headers, packageArguments };
}

function configurationSummary(entry: MCPRegistryServerResponse) {
  const { environmentVariables, headers, packageArguments } = schemaInputs(entry);
  const inputs = [...headers, ...environmentVariables, ...packageArguments];
  const required = inputs.filter((field) => field.isRequired);
  const secret = inputs.filter((field) => field.isSecret);

  return {
    requiredCount: required.length,
    secretCount: secret.length,
    totalCount: inputs.length,
  };
}

function editServerUrl(organizationId: string, serverName: string, version: string) {
  return `/org/${encodeURIComponent(organizationId)}/registry/edit/${serverName
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?version=${encodeURIComponent(version)}`;
}

function displayDate(value: string | undefined) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function parseMarkdown(markdown: string) {
  const blocks: MarkdownBlock[] = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code", code: codeLines.join("\n") });
      index += 1;
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      blocks.push({
        type: "heading",
        level: heading[1].length,
        text: heading[2],
      });
      index += 1;
      continue;
    }

    if (/^[-*_]{3,}$/.test(trimmed)) {
      blocks.push({ type: "hr" });
      index += 1;
      continue;
    }

    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      const orderedList = Boolean(ordered);
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(orderedList ? /^\d+\.\s+(.+)$/ : /^[-*]\s+(.+)$/);
        if (!item) {
          break;
        }
        items.push(item[1]);
        index += 1;
      }
      blocks.push({ type: "list", ordered: orderedList, items });
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoteLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "blockquote", lines: quoteLines });
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim()) {
      const current = lines[index].trim();
      if (
        current.startsWith("```") ||
        current.match(/^(#{1,4})\s+(.+)$/) ||
        current.match(/^[-*]\s+(.+)$/) ||
        current.match(/^\d+\.\s+(.+)$/) ||
        current.startsWith(">")
      ) {
        break;
      }
      paragraph.push(current);
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
  }

  return blocks;
}

function inlineMarkdown(text: string) {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s)]+))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(
        <code className="rounded bg-muted px-1 py-0.5 text-[0.9em]" key={`${match.index}-code`}>
          {token.slice(1, -1)}
        </code>
      );
    } else {
      const label = match[2] || match[4] || token;
      const href = match[3] || match[4] || token;
      nodes.push(
        <a
          className="text-primary underline-offset-4 hover:underline"
          href={href}
          key={`${match.index}-link`}
          rel="noreferrer"
          target="_blank"
        >
          {label}
        </a>
      );
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

function MarkdownDescription({ content }: { content: string }) {
  const blocks = parseMarkdown(content);

  return (
    <div className="space-y-4 text-sm leading-6">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          const className =
            block.level === 1
              ? "pt-1 text-2xl font-semibold tracking-normal"
              : block.level === 2
                ? "pt-4 text-xl font-semibold tracking-normal"
                : "pt-3 text-base font-semibold tracking-normal";
          const HeadingTag = `h${Math.min(block.level + 1, 4)}` as "h2" | "h3" | "h4";
          return (
            <HeadingTag className={className} key={`heading-${index}`}>
              {inlineMarkdown(block.text)}
            </HeadingTag>
          );
        }
        if (block.type === "paragraph") {
          return (
            <p className="text-muted-foreground" key={`paragraph-${index}`}>
              {inlineMarkdown(block.text)}
            </p>
          );
        }
        if (block.type === "list") {
          const ListTag = block.ordered ? "ol" : "ul";
          return (
            <ListTag
              className={`space-y-1 pl-5 text-muted-foreground ${block.ordered ? "list-decimal" : "list-disc"}`}
              key={`list-${index}`}
            >
              {block.items.map((item, itemIndex) => (
                <li key={`list-${index}-${itemIndex}`}>{inlineMarkdown(item)}</li>
              ))}
            </ListTag>
          );
        }
        if (block.type === "code") {
          return (
            <pre
              className="overflow-x-auto rounded-md border bg-muted p-3 text-xs leading-5"
              key={`code-${index}`}
            >
              <code>{block.code}</code>
            </pre>
          );
        }
        if (block.type === "blockquote") {
          return (
            <blockquote
              className="border-l-2 pl-4 text-sm leading-6 text-muted-foreground"
              key={`blockquote-${index}`}
            >
              {block.lines.map((line, lineIndex) => (
                <p key={`blockquote-${index}-${lineIndex}`}>{inlineMarkdown(line)}</p>
              ))}
            </blockquote>
          );
        }
        return <hr className="border-border" key={`hr-${index}`} />;
      })}
    </div>
  );
}

async function getServer(context: WorkspaceContext, serverName: string, version: string) {
  const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
  const path = organizationMcpRegistryPath(
    context,
    `/servers/${encodedName}/versions/${encodeURIComponent(version)}`
  );
  if (!path) {
    return null;
  }
  const cookie = await backendCookieHeader();
  const response = await fetch(backendPath(path), {
    cache: "no-store",
    headers: cookie ? { cookie } : {},
  });
  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as MCPRegistryServerResponse;
}

async function getVersions(context: WorkspaceContext, serverName: string) {
  const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
  const path = organizationMcpRegistryPath(context, `/servers/${encodedName}/versions`);
  if (!path) {
    return [];
  }
  const cookie = await backendCookieHeader();
  const response = await fetch(backendPath(path), {
    cache: "no-store",
    headers: cookie ? { cookie } : {},
  });
  if (!response.ok) {
    return [];
  }
  const data = (await response.json()) as { servers?: MCPRegistryServerResponse[] };
  return data.servers ?? [];
}

async function getInstallation(serverName: string, context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  if (!path) {
    return null;
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return null;
    }
    const data = (await response.json()) as MCPServerInstallationListResponse;
    return data.installations.find((installation) => installation.serverName === serverName) ?? null;
  } catch {
    return null;
  }
}

function statusLabel(installation: MCPServerInstallationRead | null) {
  if (!installation) {
    return "Not configured";
  }
  if (installation.status === "enabled") {
    return "Configured";
  }
  return installation.status.replaceAll("_", " ");
}

export default async function RegistryServerPage({
  params,
  searchParams,
}: RegistryServerPageProps) {
  const { organizationId, serverName } = await params;
  const { version } = await searchParams;
  const decodedName = serverName.map(decodeURIComponent).join("/");
  const selectedVersion = version || "latest";
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const response = await getServer(workspaceContext, decodedName, selectedVersion);

  if (!response) {
    notFound();
  }

  const [installation, versions] = await Promise.all([
    getInstallation(response.server.name, workspaceContext),
    getVersions(workspaceContext, response.server.name),
  ]);
  const officialMeta = response._meta["io.modelcontextprotocol.registry/official"];
  const links = sourceLinks(response);
  const config = configurationSummary(response);
  const inputs = schemaInputs(response);
  const allInputs = [...inputs.headers, ...inputs.environmentVariables, ...inputs.packageArguments];
  const packages = response.server.packages ?? [];
  const remotes = response.server.remotes ?? [];

  return (
    <AppShell
      active="registry"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={editServerUrl(organizationId, response.server.name, response.server.version)}>
            <Pencil className="size-4" />
            Edit
          </Link>
        </Button>
      }
      eyebrow="MCP Registry"
      title={response.server.title || response.server.name}
      workspaceContext={workspaceContext}
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <Card>
            <CardContent className="space-y-3 p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={installation ? "success" : "outline"} className="font-normal">
                  {statusLabel(installation)}
                </Badge>
                <Badge variant="outline" className="font-normal">
                  Version {response.server.version}
                </Badge>
                {repository(response) ? (
                  <Badge variant="outline" className="font-normal">
                    {stringValue(repository(response)?.source) || "source"}
                  </Badge>
                ) : null}
              </div>
              <div className="break-all text-sm text-muted-foreground">{response.server.name}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Description</CardTitle>
            </CardHeader>
            <CardContent>
              <MarkdownDescription content={response.server.description} />
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-5">
          <ServerVersionSelector
            currentVersion={response.server.version}
            organizationId={organizationId}
            serverName={response.server.name}
            versions={(versions.length > 0 ? versions : [response]).map((versionEntry) => ({
              isDefault:
                versionEntry._meta["io.modelcontextprotocol.registry/official"].isLatest,
              version: versionEntry.server.version,
            }))}
          />

          <Card>
            <CardHeader>
              <CardTitle>Configuration</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-2">
                {config.requiredCount > 0 ? (
                  <Badge variant="outline" className="gap-1.5 font-normal">
                    <KeyRound className="size-3.5" />
                    {config.requiredCount} required
                  </Badge>
                ) : (
                  <Badge variant="outline" className="gap-1.5 font-normal">
                    <ShieldCheck className="size-3.5" />
                    No required inputs
                  </Badge>
                )}
                {config.secretCount > 0 ? (
                  <Badge variant="outline" className="font-normal">
                    {config.secretCount} secret
                  </Badge>
                ) : null}
              </div>
              {allInputs.length > 0 ? (
                <div className="space-y-2">
                  {allInputs.map((field, index) => (
                    <div
                      className="rounded-md border p-2"
                      key={`${response.server.name}-input-${index}`}
                    >
                      <div className="break-all font-medium">
                        {stringValue(field.name) || stringValue(field.type) || "Input"}
                      </div>
                      {stringValue(field.description) ? (
                        <div className="mt-1 text-xs leading-5 text-muted-foreground">
                          {stringValue(field.description)}
                        </div>
                      ) : null}
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {field.isRequired ? <Badge variant="outline">Required</Badge> : null}
                        {field.isSecret ? <Badge variant="outline">Secret</Badge> : null}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-muted-foreground">No connection settings are required.</div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Distribution</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {remotes.length > 0 ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 font-medium">
                    <Network className="size-4 text-muted-foreground" />
                    Remote endpoints
                  </div>
                  {remotes.map((remote, index) => {
                    const value = remote as Record<string, unknown>;
                    return (
                      <div className="break-all rounded-md border p-2" key={`remote-${index}`}>
                        <div>{runtimeDisplayName(stringValue(value.type) || "remote")}</div>
                        <div className="text-xs text-muted-foreground">{stringValue(value.url)}</div>
                      </div>
                    );
                  })}
                </div>
              ) : null}

              {packages.length > 0 ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 font-medium">
                    <Package className="size-4 text-muted-foreground" />
                    Packages
                  </div>
                  {packages.map((packageDefinition, index) => {
                    const value = packageDefinition as Record<string, unknown>;
                    return (
                      <div className="break-all rounded-md border p-2" key={`package-${index}`}>
                        <div>{runtimeDisplayName(stringValue(value.registryType) || "package")}</div>
                        <div className="text-xs text-muted-foreground">
                          {stringValue(value.identifier)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </CardContent>
          </Card>

          {links.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Source</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {links.map((link) => (
                  <a
                    className="flex items-center gap-2 text-primary hover:underline"
                    href={link.url}
                    key={link.url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {link.label === "Repository" ? (
                      <GitBranch className="size-4" />
                    ) : link.label === "Website" ? (
                      <Globe className="size-4" />
                    ) : (
                      <ExternalLink className="size-4" />
                    )}
                    <span>{link.label}</span>
                  </a>
                ))}
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Registry</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <div className="capitalize">{officialMeta.status}</div>
              {displayDate(officialMeta.publishedAt) ? (
                <div className="text-muted-foreground">
                  Published {displayDate(officialMeta.publishedAt)}
                </div>
              ) : null}
              {displayDate(officialMeta.updatedAt) ? (
                <div className="text-muted-foreground">
                  Updated {displayDate(officialMeta.updatedAt)}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </aside>
      </div>
    </AppShell>
  );
}
