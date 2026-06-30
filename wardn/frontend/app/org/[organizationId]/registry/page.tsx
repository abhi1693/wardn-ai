import { redirect } from "next/navigation";

type OrganizationRegistryRedirectPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationRegistryRedirectPage({
  params,
}: OrganizationRegistryRedirectPageProps) {
  const { organizationId } = await params;
  redirect(`/org/${encodeURIComponent(organizationId)}/catalog`);
}
