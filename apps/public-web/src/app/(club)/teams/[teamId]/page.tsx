import { notFound } from "next/navigation";

import { siteTranslator } from "@/lib/i18n";
import { getSite, getSquad, getTeams } from "@/lib/site";
import { templateFor } from "@/templates";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ teamId: string }>;
}) {
  const { teamId } = await params;
  const team = (await getTeams()).find((candidate) => candidate.id === teamId);
  return { title: team?.name ?? "Team" };
}

export default async function TeamPage({
  params,
}: {
  params: Promise<{ teamId: string }>;
}) {
  const { teamId } = await params;
  const site = await getSite();
  if (!site) notFound();

  const team = (await getTeams()).find((candidate) => candidate.id === teamId);
  if (!team) notFound();

  const squad = await getSquad(teamId);
  const { TeamView } = templateFor(site.branding.template);
  return <TeamView site={site} team={team} squad={squad} i18n={await siteTranslator(site)} />;
}
