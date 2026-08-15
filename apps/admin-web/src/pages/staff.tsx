import {
  TEAM_STAFF_ROLES,
  useInviteStaff,
  useAddTeamStaff,
  useRemoveTeamStaff,
  useStaff,
  useStaffRoles,
  useTeamStaff,
  useTeams,
  useUpdateTeamStaff,
  type StaffMember,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Section,
  Select,
  Skeleton,
  Switch,
  useToast,
} from "@footbola/ui";
import { UserRound, Users } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";

/**
 * The people at the club.
 *
 * Two different things live here, and putting them on one page is deliberate:
 * a club administrator thinking "I need to add the U15 coach" does not know or
 * care that one of these is a public presentation and the other is an account
 * with permissions. They are told apart by what they answer:
 *
 *   **Staff tehnic** — who runs a team, shown on the club's website. No login.
 *   **Conturi** — who can sign in to this admin, and what they may touch.
 *
 * The coach was previously only reachable from inside the team dialog, which
 * is where nobody looked for it.
 */

function TeamStaffSection() {
  const { t } = useI18n();
  const toast = useToast();
  const teams = useTeams();
  const [teamId, setTeamId] = useState("");
  // Default to the first team once they arrive, so the section is never an
  // empty box waiting for a choice nobody knew they had to make.
  const chosen = teamId || teams.data?.[0]?.id || "";

  const staff = useTeamStaff(chosen || null);
  const add = useAddTeamStaff();
  const update = useUpdateTeamStaff();
  const remove = useRemoveTeamStaff();

  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [role, setRole] = useState<string>("HEAD_COACH");

  function submit() {
    if (!chosen) return;
    add.mutate(
      { teamId: chosen, input: { first_name: first.trim(), last_name: last.trim(), role } },
      {
        onSuccess: () => {
          setFirst("");
          setLast("");
          toast.success(t("staff", "added"));
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  const rows = staff.data ?? [];

  return (
    <Section title={t("staff", "technical")} description={t("staff", "technicalHint")}>
      <Card className="space-y-4 p-4">
        <Field label={t("staff", "team")}>
          {(props) => (
            <Select
              {...props}
              value={chosen}
              onChange={setTeamId}
              options={(teams.data ?? []).map((team) => ({
                value: team.id,
                label: team.name,
              }))}
            />
          )}
        </Field>

        {staff.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : rows.length === 0 ? (
          <p className="text-xs text-text-secondary">{t("staff", "technicalEmpty")}</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {rows.map((member) => (
              <li key={member.id} className="flex items-center gap-3 px-3 py-2.5">
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-brand-subtle text-brand-text">
                  <UserRound className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-text">
                    {member.name}
                  </span>
                  <span className="block text-xs text-text-secondary">
                    {member.title ?? t("squads", `role${member.role}` as "roleHEAD_COACH")}
                  </span>
                </span>
                <Switch
                  checked={member.is_public}
                  onChange={(next) =>
                    update.mutate({
                      teamId: chosen,
                      staffId: member.id,
                      changes: { is_public: next },
                    })
                  }
                  label={t("staff", "onWebsite")}
                />
                <Button
                  variant="ghost"
                  className="text-danger"
                  onClick={() => remove.mutate({ teamId: chosen, staffId: member.id })}
                >
                  {t("common", "delete")}
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
          <Field label={t("staff", "firstName")}>
            {(props) => (
              <Input {...props} value={first} onChange={(e) => setFirst(e.target.value)} />
            )}
          </Field>
          <Field label={t("staff", "lastName")}>
            {(props) => (
              <Input {...props} value={last} onChange={(e) => setLast(e.target.value)} />
            )}
          </Field>
          <Field label={t("staff", "role")}>
            {(props) => (
              <Select
                {...props}
                value={role}
                onChange={setRole}
                options={TEAM_STAFF_ROLES.map((value) => ({
                  value,
                  label: t("squads", `role${value}` as "roleHEAD_COACH"),
                }))}
              />
            )}
          </Field>
          <Button
            onClick={submit}
            loading={add.isPending}
            disabled={!chosen || !first.trim() || !last.trim()}
          >
            {t("staff", "add")}
          </Button>
        </div>
      </Card>
    </Section>
  );
}

function AccountRow({ member }: { member: StaffMember }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-bg-muted text-text-secondary">
        <Users className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-text">
          {member.display_name}
        </span>
        <span className="block truncate text-xs text-text-secondary">{member.email}</span>
      </span>
      <span className="hidden text-xs text-text-secondary sm:block">
        {member.scope_label}
      </span>
      <Badge tone={member.pending ? "warning" : "neutral"}>
        {member.pending ? t("staff", "pending") : member.role_name}
      </Badge>
    </li>
  );
}

/**
 * Giving somebody a login.
 *
 * The role list comes from the server already marked with what this caller may
 * hand out, so a club administrator is never offered a role that will be
 * refused. Two ways in: an invitation link, which is the default and the
 * better one, or a starting password for the coach who has no working email —
 * marked temporary, so it stops being a credential the moment it is used.
 */
function InviteForm({ clubId }: { clubId: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const teams = useTeams();
  const [teamId, setTeamId] = useState("");
  // Re-asked once a team is chosen: a team-scoped role cannot be judged
  // without one, and asking without it made Coach look forbidden when it was
  // only unanswerable.
  const roles = useStaffRoles(clubId, teamId || undefined);
  const invite = useInviteStaff();

  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("CONTENT_MANAGER");
  const [password, setPassword] = useState("");

  const chosen = (roles.data ?? []).find((row) => row.key === role);
  const needsTeam = chosen?.scope_level === "TEAM";

  function submit() {
    invite.mutate(
      {
        email: email.trim(),
        first_name: first.trim(),
        last_name: last.trim(),
        role,
        club_id: clubId,
        team_id: needsTeam ? teamId || null : null,
        temporary_password: password.trim() || null,
      },
      {
        onSuccess: () => {
          setFirst("");
          setLast("");
          setEmail("");
          setPassword("");
          toast.success(
            password.trim()
              ? t("staff", "invitedWithPassword")
              : t("staff", "invitedByLink"),
          );
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  const ready =
    first.trim() && last.trim() && email.includes("@") && (!needsTeam || teamId);

  return (
    <div className="rounded-lg border border-dashed border-border p-4">
      <p className="text-sm font-medium text-text">{t("staff", "inviteTitle")}</p>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">{t("staff", "inviteHint")}</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("staff", "firstName")}>
          {(props) => (
            <Input {...props} value={first} onChange={(e) => setFirst(e.target.value)} />
          )}
        </Field>
        <Field label={t("staff", "lastName")}>
          {(props) => (
            <Input {...props} value={last} onChange={(e) => setLast(e.target.value)} />
          )}
        </Field>
        <Field label={t("staff", "email")} className="sm:col-span-2">
          {(props) => (
            <Input
              {...props}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="antrenor@clubul-tau.ro"
            />
          )}
        </Field>

        <Field label={t("staff", "accessRole")} help={chosen?.description}>
          {(props) => (
            <Select
              {...props}
              value={role}
              onChange={setRole}
              options={(roles.data ?? []).map((row) => {
                const name = t("staff", `role${row.key}` as "roleCOACH");
                // Three states, not two. A team-scoped role with no team
                // chosen is not forbidden — it is unanswerable, and saying
                // "beyond your access" about it was simply wrong.
                if (row.scope_level === "TEAM" && !teamId) {
                  return { value: row.key, label: `${name} — ${t("staff", "pickTeamFirst")}` };
                }
                return {
                  value: row.key,
                  label: row.grantable ? name : `${name} — ${t("staff", "outOfReach")}`,
                };
              })}
            />
          )}
        </Field>

        {needsTeam && (
          <Field label={t("staff", "team")}>
            {(props) => (
              <Select
                {...props}
                value={teamId}
                onChange={setTeamId}
                placeholder={t("staff", "chooseTeam")}
                options={(teams.data ?? []).map((team) => ({
                  value: team.id,
                  label: team.name,
                }))}
              />
            )}
          </Field>
        )}

        <Field
          label={t("staff", "startingPassword")}
          help={t("staff", "startingPasswordHint")}
          className="sm:col-span-2"
        >
          {(props) => (
            <Input
              {...props}
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t("staff", "startingPasswordPlaceholder")}
            />
          )}
        </Field>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Button onClick={submit} loading={invite.isPending} disabled={!ready}>
          {password.trim() ? t("staff", "createAccount") : t("staff", "sendInvite")}
        </Button>
        {chosen && !chosen.grantable && !(chosen.scope_level === "TEAM" && !teamId) && (
          <span className="text-xs text-warning">{t("staff", "roleOutOfReach")}</span>
        )}
      </div>
    </div>
  );
}

function AccountsSection() {
  const { t } = useI18n();
  const { club } = useSession();
  const accounts = useStaff();

  return (
    <Section title={t("staff", "accounts")} description={t("staff", "accountsHint")}>
      <Card className="space-y-4 p-4">
        {accounts.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (accounts.data?.length ?? 0) === 0 ? (
          <p className="text-xs text-text-secondary">{t("staff", "accountsEmpty")}</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {(accounts.data ?? []).map((member) => (
              <AccountRow key={`${member.user_id}-${member.role_key}`} member={member} />
            ))}
          </ul>
        )}

        {club && <InviteForm clubId={club.id} />}
      </Card>
    </Section>
  );
}

export function StaffPage() {
  const { t } = useI18n();
  const { can } = useSession();

  if (!can("staff.profile.read")) {
    return (
      <EmptyState
        icon={<Users className="size-5" />}
        title={t("staff", "noAccess")}
        description={t("staff", "noAccessBody")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("staff", "eyebrow")}
        title={t("staff", "title")}
        description={t("staff", "description")}
      />
      <TeamStaffSection />
      {can("authz.role.read") && <AccountsSection />}
    </div>
  );
}
