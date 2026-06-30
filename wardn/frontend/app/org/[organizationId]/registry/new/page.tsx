import { redirect } from "next/navigation";

type NewRegistryServerRedirectPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewRegistryServerRedirectPage({
  params,
}: NewRegistryServerRedirectPageProps) {
  const { organizationId } = await params;
  redirect(`/org/${encodeURIComponent(organizationId)}/catalog/new`);
}
