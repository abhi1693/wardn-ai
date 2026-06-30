import { redirect } from "next/navigation";

type NewCatalogServerVersionRedirectPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewCatalogServerVersionRedirectPage({
  params,
}: NewCatalogServerVersionRedirectPageProps) {
  const { organizationId } = await params;
  redirect(`/org/${encodeURIComponent(organizationId)}/catalog`);
}
