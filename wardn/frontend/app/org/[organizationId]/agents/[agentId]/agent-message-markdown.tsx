"use client";

import type { UIMessage } from "ai";
import { Check, Copy } from "lucide-react";
import { type ComponentPropsWithoutRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/atoms/button";
import { cn } from "@/lib/utils";

type MessageRole = UIMessage["role"];

function markdownText(children: ComponentPropsWithoutRef<"code">["children"]) {
  return Array.isArray(children) ? children.join("") : String(children ?? "");
}

function MarkdownCode({
  children,
  className,
  ...props
}: ComponentPropsWithoutRef<"code"> & { node?: unknown }) {
  const [copied, setCopied] = useState(false);
  const rawCode = markdownText(children).replace(/\n$/, "");
  const language = /language-(\S+)/.exec(className ?? "")?.[1] ?? "";
  const isBlock = Boolean(language) || rawCode.includes("\n");

  if (!isBlock) {
    return (
      <code className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[0.88em]" {...props}>
        {children}
      </code>
    );
  }

  async function copyCode() {
    await navigator.clipboard.writeText(rawCode);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="my-3 overflow-hidden rounded-md border border-border bg-[#0b0f14] text-[#e7ebf0]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="font-mono text-xs text-[#a7b1bd]">{language || "code"}</span>
        <Button
          className="h-7 border-white/15 bg-white/5 px-2 text-xs text-white hover:bg-white/10"
          onClick={copyCode}
          size="sm"
          type="button"
          variant="outline"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="overflow-x-auto p-3 text-sm leading-6">
        <code className={className} {...props}>{rawCode}</code>
      </pre>
    </div>
  );
}

function markdownComponents(role: MessageRole): Components {
  const isUser = role === "user";
  const subtleText = isUser ? "text-primary-foreground/80" : "text-muted-foreground";
  return {
    p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
    a: ({ children, href }) => (
      <a
        className={cn("font-medium underline underline-offset-4", isUser ? "text-primary-foreground" : "text-foreground")}
        href={href}
        rel="noreferrer"
        target="_blank"
      >
        {children}
      </a>
    ),
    code: MarkdownCode,
    pre: ({ children }) => <>{children}</>,
    ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
    ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
    li: ({ children }) => <li className="pl-1">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className={cn("my-3 border-l-2 pl-3", isUser ? "border-primary-foreground/40" : "border-border", subtleText)}>
        {children}
      </blockquote>
    ),
    h1: ({ children }) => <h1 className="mb-3 text-lg font-semibold">{children}</h1>,
    h2: ({ children }) => <h2 className="mb-2 text-base font-semibold">{children}</h2>,
    h3: ({ children }) => <h3 className="mb-2 text-sm font-semibold">{children}</h3>,
    table: ({ children }) => <div className="my-3 overflow-x-auto"><table className="w-full border-collapse text-left text-sm">{children}</table></div>,
    th: ({ children }) => <th className="border border-border px-2 py-1">{children}</th>,
    td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
    hr: () => <hr className="my-4 border-border" />,
  };
}

export function AgentMessageMarkdown({ role, text }: { role: MessageRole; text: string }) {
  return (
    <ReactMarkdown components={markdownComponents(role)} remarkPlugins={[remarkGfm]}>
      {text}
    </ReactMarkdown>
  );
}
