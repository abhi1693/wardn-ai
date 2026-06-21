import { ArrowRight, BookOpen, Server, SquareActivity, Waypoints } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const metrics = [
  { label: "Installed Servers", value: "0", icon: Server },
  { label: "Active Sessions", value: "0", icon: Waypoints },
  { label: "Tool Calls Today", value: "0", icon: SquareActivity },
];

export default function Dashboard() {
  return (
    <AppShell active="dashboard" eyebrow="Operations" title="Dashboard">
      <section className="grid gap-4 md:grid-cols-3" aria-label="Gateway metrics">
        {metrics.map((metric) => {
          const Icon = metric.icon;
          return (
            <Card key={metric.label}>
              <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {metric.label}
                </CardTitle>
                <Icon className="size-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-semibold">{metric.value}</div>
              </CardContent>
            </Card>
          );
        })}
      </section>

      <Card>
        <CardContent className="flex min-h-72 flex-col items-start p-6">
          <div className="mt-auto max-w-xl">
            <BookOpen className="mb-4 size-8 text-muted-foreground" />
            <h2 className="text-xl font-semibold">No gateway activity yet</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Activity will appear here after your organization installs a supported server.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button asChild>
                <Link href="/registry">
                  View registry
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </AppShell>
  );
}
