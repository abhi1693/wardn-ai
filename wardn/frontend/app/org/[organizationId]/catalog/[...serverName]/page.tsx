import { redirect } from "next/navigation";

type CatalogServerRedirectPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function CatalogServerRedirectPage({
  params,
}: CatalogServerRedirectPageProps) {
  const { organizationId } = await params;
  redirect(`/org/${encodeURIComponent(organizationId)}/catalog`);
}
