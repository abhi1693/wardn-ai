"use client";

import { ArrowRight, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/atoms/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/atoms/command";

export type CommandDestination = {
  group: string;
  href: string;
  label: string;
};

type DesktopCommandMenuProps = {
  destinations: CommandDestination[];
  onNavigate: (href: string) => void;
};

export function DesktopCommandMenu({ destinations, onNavigate }: DesktopCommandMenuProps) {
  const [open, setOpen] = useState(false);
  const groupedDestinations = useMemo(() => {
    const groups = new Map<string, CommandDestination[]>();
    for (const destination of destinations) {
      const group = groups.get(destination.group) ?? [];
      group.push(destination);
      groups.set(destination.group, group);
    }
    return Array.from(groups.entries());
  }, [destinations]);

  useEffect(() => {
    function openCommandMenu(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    }

    document.addEventListener("keydown", openCommandMenu);
    return () => document.removeEventListener("keydown", openCommandMenu);
  }, []);

  function navigate(href: string) {
    setOpen(false);
    onNavigate(href);
  }

  return (
    <>
      <Button
        aria-label="Open command menu"
        className="h-8 w-40 justify-start gap-2 border-border bg-background px-2.5 text-muted-foreground shadow-none hover:bg-muted hover:text-foreground 2xl:w-52"
        onClick={() => setOpen(true)}
        type="button"
        variant="outline"
      >
        <Search className="size-3.5" />
        <span className="text-sm">Search</span>
        <kbd className="ml-auto rounded border border-border bg-muted px-1.5 py-0.5 font-sans text-[10px] leading-none text-muted-foreground">
          Ctrl K
        </kbd>
      </Button>
      <CommandDialog onOpenChange={setOpen} open={open}>
        <CommandInput aria-label="Search destinations" placeholder="Search destinations..." />
        <CommandList>
          <CommandEmpty>No matching destination.</CommandEmpty>
          {groupedDestinations.map(([group, items]) => (
            <CommandGroup heading={group} key={group}>
              {items.map((destination) => (
                <CommandItem
                  key={`${destination.group}:${destination.href}`}
                  onSelect={() => navigate(destination.href)}
                  value={`${destination.label} ${destination.group}`}
                >
                  <span>{destination.label}</span>
                  <ArrowRight className="ml-auto text-muted-foreground" />
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
      </CommandDialog>
    </>
  );
}

export function AppShellCommandMenu({ destinations }: { destinations: CommandDestination[] }) {
  const router = useRouter();
  return <DesktopCommandMenu destinations={destinations} onNavigate={(href) => router.push(href)} />;
}
