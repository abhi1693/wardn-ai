import { redirect } from "next/navigation";

type RegistryServerRedirectPageProps = {
  params: Promise<{ organizationId: string; serverName: string[] }>;
  searchParams: Promise<{ version?: string }>;
};

export default async function RegistryServerRedirectPage({
  params,
  searchParams,
}: RegistryServerRedirectPageProps) {
  const { organizationId, serverName } = await params;
  const { version } = await searchParams;
  const encodedName = serverName.map(encodeURIComponent).join("/");
  const query = version ? `?version=${encodeURIComponent(version)}` : "";
  redirect(`/org/${encodeURIComponent(organizationId)}/catalog/${encodedName}${query}`);
}
