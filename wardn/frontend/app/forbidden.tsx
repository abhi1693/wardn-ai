import Link from "next/link";

import { BrandMark } from "@/app/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export default function Forbidden() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-5">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <div className="mb-4 flex items-center gap-3">
            <BrandMark priority />
            <span className="text-sm font-semibold">Wardn AI</span>
          </div>
          <h1 className="text-xl font-semibold">Access denied</h1>
          <CardDescription>
            You are signed in, but you do not have permission to view this resource.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link href="/org">Choose another organization</Link>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
