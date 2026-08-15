import { notFound } from "next/navigation";

import { siteTranslator } from "@/lib/i18n";
import type { SquadPlayer, TeamStaffMember } from "@/lib/site";
import { getSite, getSquad, getTeamStaff, getTeams } from "@/lib/site";
import { TeamsShowcase } from "@/templates/squads";

export const metadata = { title: "Teams" };

export default async function TeamsPage() {
  const site = await getSite();
  if (!site) notFound();

  const [i18n, teams] = await Promise.all([siteTranslator(site), getTeams()]);

  // Squad sizes are part of how a team reads on this page, so they are fetched
  // here rather than on the detail page alone. One request per team, all in
  // parallel and all cached the same way the page is — a club has a dozen
  // teams, not a thousand.
  const [rosters, staff] = await Promise.all([
    Object.fromEntries(
      await Promise.all(
        teams.map(async (team) => [team.id, await getSquad(team.id)] as const),
      ),
    ) as Record<string, SquadPlayer[]>,
    Object.fromEntries(
      await Promise.all(
        teams.map(async (team) => [team.id, await getTeamStaff(team.id)] as const),
      ),
    ) as Record<string, TeamStaffMember[]>,
  ]);

  return (
    <TeamsShowcase
      site={site}
      teams={teams}
      rosters={rosters}
      staff={staff}
      labels={{
        title: i18n.t("publicSite", "ourTeams"),
        lead: i18n.t("publicSite", "teamsLead"),
        firstTeam: i18n.t("publicSite", "firstTeam"),
        senior: i18n.t("publicSite", "senior"),
        academy: i18n.t("publicSite", "academy"),
        academyGroups: i18n.t("publicSite", "academyGroups"),
        teams: i18n.t("publicSite", "teams"),
        players: i18n.t("publicSite", "registeredPlayers"),
        viewSquad: i18n.t("publicSite", "viewSquad"),
        squad: i18n.t("publicSite", "squad"),
        squadComingSoon: i18n.t("publicSite", "squadComingSoon"),
        playerCount: (count: number) => i18n.plural("publicSite", "playerCount", count),
        staffRole: (role: string) =>
          i18n.t("publicSite", `role${role}` as "roleHEAD_COACH"),
      }}
    />
  );
}
