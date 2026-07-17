import Link from "next/link";

import { BrandMark } from "@/app/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-5">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <div className="mb-4 flex items-center gap-3">
            <BrandMark priority />
            <span className="text-sm font-semibold">Wardn AI</span>
          </div>
          <h1 className="text-xl font-semibold">Page not found</h1>
          <CardDescription>
            This resource does not exist or is no longer available.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link href="/org">Choose an organization</Link>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
