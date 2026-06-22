import { redirect } from "next/navigation";

type OrganizationLandingPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationLandingPage({ params }: OrganizationLandingPageProps) {
  const { organizationId } = await params;

  redirect(`/org/${encodeURIComponent(organizationId)}/dashboard`);
}
