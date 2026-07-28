import { redirect } from "next/navigation";

type MyUsagePageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function MyUsagePage({ params }: MyUsagePageProps) {
  const { organizationId } = await params;
  redirect(`/org/${encodeURIComponent(organizationId)}/usage?scope=me`);
}
