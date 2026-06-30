import { redirect } from "next/navigation";

type EditRegistryServerRedirectPageProps = {
  params: Promise<{ organizationId: string; serverName: string[] }>;
  searchParams: Promise<{ version?: string }>;
};

export default async function EditRegistryServerRedirectPage({
  params,
  searchParams,
}: EditRegistryServerRedirectPageProps) {
  const { organizationId, serverName } = await params;
  const { version } = await searchParams;
  const encodedName = serverName.map(encodeURIComponent).join("/");
  const query = version ? `?version=${encodeURIComponent(version)}` : "";
  redirect(`/org/${encodeURIComponent(organizationId)}/catalog/edit/${encodedName}${query}`);
}
