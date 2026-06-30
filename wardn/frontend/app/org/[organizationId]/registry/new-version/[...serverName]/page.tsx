import { redirect } from "next/navigation";

type NewRegistryServerVersionRedirectPageProps = {
  params: Promise<{ organizationId: string; serverName: string[] }>;
  searchParams: Promise<{ version?: string }>;
};

export default async function NewRegistryServerVersionRedirectPage({
  params,
  searchParams,
}: NewRegistryServerVersionRedirectPageProps) {
  const { organizationId, serverName } = await params;
  const { version } = await searchParams;
  const encodedName = serverName.map(encodeURIComponent).join("/");
  const query = version ? `?version=${encodeURIComponent(version)}` : "";
  redirect(
    `/org/${encodeURIComponent(organizationId)}/catalog/new-version/${encodedName}${query}`
  );
}
