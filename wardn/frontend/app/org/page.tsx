import { Plus } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

import { getOrganizations } from "../organizations/data";

import { OrganizationSelectClient } from "./organization-select-client";

export default async function OrganizationSelectionPage() {
  const organizations = await getOrganizations();

  return (
    <main className="min-h-screen bg-background">
      <header className="flex h-16 items-center justify-between gap-4 border-b border-border bg-card px-8 max-md:px-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
            W
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold leading-5">Wardn AI</div>
            <div className="text-xs leading-4 text-muted-foreground">Select organization</div>
          </div>
        </div>
        <Button asChild size="sm">
          <Link href="/organizations/new">
            <Plus className="size-4" />
            Add organization
          </Link>
        </Button>
      </header>

      <section className="mx-auto w-full max-w-[1440px] px-8 py-7 max-md:px-4">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase leading-4 tracking-[0.08em] text-muted-foreground">
            Organization
          </p>
          <h1 className="text-2xl font-semibold leading-8 tracking-normal text-foreground">
            Select organization
          </h1>
        </header>

        {organizations.length > 0 ? (
          <OrganizationSelectClient organizations={organizations} />
        ) : (
          <Card>
            <CardContent className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
              Create an organization to begin.
            </CardContent>
          </Card>
        )}
      </section>
    </main>
  );
}
