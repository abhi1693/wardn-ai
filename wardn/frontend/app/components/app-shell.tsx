import {
  BookOpen,
  LayoutDashboard,
  ServerCog,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { LogoutButton } from "./logout-button";

const navItems = [
  { label: "Dashboard", href: "/", activeKey: "dashboard", icon: LayoutDashboard },
  { label: "MCP Registry", href: "/registry", activeKey: "registry", icon: BookOpen },
  { label: "Install", href: "/install", activeKey: "install", icon: ServerCog },
];

type AppShellProps = {
  active: "dashboard" | "registry" | "install";
  eyebrow: string;
  title: string;
  actions?: ReactNode;
  children: ReactNode;
};

export function AppShell({ active, eyebrow, title, actions, children }: AppShellProps) {
  return (
    <main className="grid min-h-screen grid-cols-[260px_minmax(0,1fr)] bg-background max-lg:grid-cols-1">
      <aside className="flex min-h-screen flex-col border-r bg-card px-4 py-5 max-lg:min-h-0 max-lg:border-r-0 max-lg:border-b">
        <div className="flex items-center gap-3 px-2">
          <div className="flex size-9 items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
            W
          </div>
          <div>
            <div className="text-sm font-semibold leading-5">Wardn AI</div>
            <div className="text-xs leading-4 text-muted-foreground">Control plane</div>
          </div>
        </div>

        <nav className="mt-8 grid gap-1 max-lg:mt-5 max-lg:grid-cols-2" aria-label="Primary">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = item.activeKey === active;
            const className = cn(
              "flex min-h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors",
              isActive && "bg-accent text-accent-foreground",
              "hover:bg-muted hover:text-foreground"
            );

            return (
              <Link className={className} href={item.href} key={item.label}>
                <Icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto max-lg:mt-5" />
      </aside>

      <section className="min-w-0 px-8 py-7 max-md:px-4">
        <header className="mb-7 flex items-start justify-between gap-4 max-md:flex-col">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              {eyebrow}
            </p>
            <h1 className="text-3xl font-semibold tracking-normal text-foreground">{title}</h1>
          </div>
          <div className="flex items-center gap-2 max-md:w-full max-md:flex-wrap">
            {actions}
            <LogoutButton />
          </div>
        </header>
        <div className="space-y-5">{children}</div>
      </section>
    </main>
  );
}
