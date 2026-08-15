import {
  TEAM_STAFF_ROLES,
  useSports,
  useAddTeamStaff,
  useCreateTeam,
  useRemoveTeamStaff,
  useTeamStaff,
  useUpdateTeam,
  useUpdateTeamStaff,
  type Team,
  type TeamUpdate,
} from "@footbola/api-client";
import {
  Button,
  Dialog,
  Field,
  Input,
  Select,
  Switch,
  useToast,
} from "@footbola/ui";
import { useState } from "react";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";

/**
 * Adding and editing a squad.
 *
 * One dialog for both: the fields are identical, and a club renaming a team is
 * doing the same thing it did when it created one. `team` being null is the
 * only difference — it decides whether this posts or patches.
 *
 * Archiving lives here too, next to the fields, because "remove this team" is
 * what a club is looking for when it opens the editor for a squad that no
 * longer runs. There is no delete: a season of registrations and results hangs
 * off a team, and deleting it would orphan all of them.
 */

const LEVELS = ["FIRST", "RESERVE", "YOUTH", "FUTSAL", "OTHER"] as const;
const GENDERS = ["MALE", "FEMALE", "MIXED"] as const;

/**
 * Who runs the team.
 *
 * Inside the team dialog rather than on its own screen, because a coach is an
 * attribute of a team the way its age group is — and a club setting up an
 * academy should not have to find a second place to say who takes the U15.
 *
 * Only shown for a team that already exists: staff need a team to belong to.
 */
function StaffSection({ teamId }: { teamId: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const staff = useTeamStaff(teamId);
  const add = useAddTeamStaff();
  const update = useUpdateTeamStaff();
  const remove = useRemoveTeamStaff();

  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [role, setRole] = useState<string>("HEAD_COACH");

  function submit() {
    add.mutate(
      { teamId, input: { first_name: first.trim(), last_name: last.trim(), role } },
      {
        onSuccess: () => {
          setFirst("");
          setLast("");
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  const rows = staff.data ?? [];

  return (
    <section className="mt-6 border-t border-border pt-5">
      <p className="text-sm font-medium text-text">{t("squads", "staff")}</p>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">{t("squads", "staffHint")}</p>

      {rows.length === 0 ? (
        <p className="mb-4 text-xs text-text-secondary">{t("squads", "staffEmpty")}</p>
      ) : (
        <ul className="mb-4 divide-y divide-border rounded-lg border border-border">
          {rows.map((member) => (
            <li key={member.id} className="flex items-center gap-3 px-3 py-2.5">
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
                    teamId,
                    staffId: member.id,
                    changes: { is_public: next },
                  })
                }
                label={t("squads", "staffPublic")}
              />
              <Button
                variant="ghost"
                className="text-danger"
                onClick={() => remove.mutate({ teamId, staffId: member.id })}
              >
                {t("squads", "staffRemove")}
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
        <Field label={t("squads", "staffFirstName")}>
          {(props) => (
            <Input {...props} value={first} onChange={(e) => setFirst(e.target.value)} />
          )}
        </Field>
        <Field label={t("squads", "staffLastName")}>
          {(props) => (
            <Input {...props} value={last} onChange={(e) => setLast(e.target.value)} />
          )}
        </Field>
        <Field label={t("squads", "staffRole")}>
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
          variant="secondary"
          onClick={submit}
          loading={add.isPending}
          disabled={!first.trim() || !last.trim()}
        >
          {t("squads", "staffAdd")}
        </Button>
      </div>
    </section>
  );
}

export function TeamEditor({
  open,
  onOpenChange,
  team,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Null to create. */
  team: Team | null;
}) {
  const { t } = useI18n();
  const { club } = useSession();
  const toast = useToast();
  const create = useCreateTeam();
  const update = useUpdateTeam();

  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [ageGroup, setAgeGroup] = useState("");
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("YOUTH");
  const [gender, setGender] = useState<(typeof GENDERS)[number]>("MALE");
  const [sport, setSport] = useState(team?.sport ?? "FOOTBALL");
  const [isAcademy, setIsAcademy] = useState(true);
  const [seeded, setSeeded] = useState<string | null>(null);

  // Seeded on the render that opens it, keyed by which team this is, so
  // reopening on a different squad re-reads rather than showing the last one.
  const key = team?.id ?? (open ? "new" : null);
  if (key && seeded !== key) {
    setSeeded(key);
    setName(team?.name ?? "");
    setCode(team?.code ?? "");
    setAgeGroup(team?.age_group ?? "");
    setLevel((team?.level as (typeof LEVELS)[number]) ?? "YOUTH");
    setGender((team?.gender as (typeof GENDERS)[number]) ?? "MALE");
    setIsAcademy(team?.is_academy ?? true);
    setSport(team?.sport ?? "FOOTBALL");
  }
  if (!open && seeded !== null) setSeeded(null);

  const busy = create.isPending || update.isPending;
  const sports = useSports();
  // A club that only plays one sport should never be asked which: the field
  // appears once there is a second one to choose, or on a team that is already
  // the exception. Everything the platform supports is still in the list —
  // this only decides whether the question is worth putting on the form.
  const showSport = (sports.data?.length ?? 0) > 1;

  function submit() {
    const fields = {
      name: name.trim(),
      code: code.trim().toUpperCase(),
      age_group: ageGroup.trim() || null,
      level,
      gender,
      is_academy: isAcademy,
      sport,
    };
    const done = {
      onSuccess: () => {
        toast.success(t("squads", team ? "updated" : "created"));
        onOpenChange(false);
      },
      onError: (error: Error) => toast.error(error.message),
    };

    if (team) update.mutate({ id: team.id, changes: fields as TeamUpdate }, done);
    else create.mutate({ club_id: club.id, ...fields }, done);
  }

  function archive(status: "ACTIVE" | "ARCHIVED") {
    if (!team) return;
    update.mutate(
      { id: team.id, changes: { status } },
      {
        onSuccess: () => {
          toast.success(t("squads", status === "ARCHIVED" ? "archived" : "updated"));
          onOpenChange(false);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("squads", team ? "editTitle" : "addTitle")}
      description={team ? undefined : t("squads", "addBody")}
      footer={
        <>
          {team && (
            <Button
              variant="ghost"
              className="mr-auto text-danger"
              onClick={() => archive(team.status === "ARCHIVED" ? "ACTIVE" : "ARCHIVED")}
              disabled={busy}
            >
              {t("squads", team.status === "ARCHIVED" ? "restore" : "archive")}
            </Button>
          )}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button onClick={submit} loading={busy} disabled={!name.trim() || !code.trim()}>
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("squads", "name")} required className="sm:col-span-2">
          {(props) => (
            <Input
              {...props}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Under 15"
            />
          )}
        </Field>

        <Field label={t("squads", "code")} help={t("squads", "codeHint")} required>
          {(props) => (
            <Input
              {...props}
              value={code}
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              maxLength={16}
            />
          )}
        </Field>

        <Field label={t("squads", "ageGroup")}>
          {(props) => (
            <Input
              {...props}
              value={ageGroup}
              onChange={(event) => setAgeGroup(event.target.value)}
              placeholder={t("squads", "ageGroupPlaceholder")}
              maxLength={16}
            />
          )}
        </Field>

        <Field label={t("squads", "level")}>
          {(props) => (
            <Select
              {...props}
              value={level}
              onChange={setLevel}
              options={LEVELS.map((value) => ({
                value,
                label: t("squads", `level${value}` as "levelFIRST"),
              }))}
            />
          )}
        </Field>

        <Field label={t("squads", "gender")}>
          {(props) => (
            <Select
              {...props}
              value={gender}
              onChange={setGender}
              options={GENDERS.map((value) => ({
                value,
                label: t("squads", `gender${value}` as "genderMALE"),
              }))}
            />
          )}
        </Field>

        {showSport && (
          <Field
            label={t("squads", "sport")}
            help={t("squads", "sportHint")}
            className="sm:col-span-2"
          >
            {(props) => (
              <Select
                {...props}
                value={sport}
                onChange={setSport}
                options={(sports.data ?? []).map((option) => ({
                  value: option.key,
                  label: t("squads", `sport${option.key}` as "sportFOOTBALL"),
                }))}
              />
            )}
          </Field>
        )}

        <div className="sm:col-span-2">
          <label className="flex items-center gap-2.5 text-sm text-text">
            <Switch
              checked={isAcademy}
              onChange={setIsAcademy}
              label={t("squads", "isAcademy")}
            />
            {t("squads", "isAcademy")}
          </label>
          <p className="mt-1 text-xs text-text-secondary">{t("squads", "isAcademyHint")}</p>
        </div>
      </div>

      {team && <StaffSection teamId={team.id} />}
    </Dialog>
  );
}
