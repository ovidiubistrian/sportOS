import {
  useChangeRegistration,
  useTeams,
  useUpdatePlayer,
  type PlayerDetail,
} from "@footbola/api-client";
import {
  Button,
  Dialog,
  Field,
  Input,
  Segmented,
  Select,
  Separator,
  useToast,
} from "@footbola/ui";
import { useState } from "react";

import { useI18n } from "../app/locale";
import { ImageField } from "./site/image-field";

/**
 * Editing a player.
 *
 * Two things in one dialog because a club opening a player thinks of them as
 * one record, but they are not one write: the details are a PATCH, and the
 * squad is a new registration — moving a player ends the old one so last
 * season's team sheet stays true. Two save buttons rather than one, so the
 * dialog does not quietly imply otherwise.
 */

const POSITIONS = ["GK", "RB", "CB", "LB", "DM", "CM", "AM", "RW", "LW", "ST"] as const;
const FEET = ["LEFT", "RIGHT", "BOTH"] as const;
const STATUSES = ["TRIAL", "REGISTERED", "LOANED_OUT", "INACTIVE", "DEPARTED"] as const;

export function PlayerEditor({
  open,
  onOpenChange,
  player,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  player: PlayerDetail;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const teams = useTeams();
  const save = useUpdatePlayer();
  const move = useChangeRegistration();

  const [firstName, setFirstName] = useState(player.first_name);
  const [lastName, setLastName] = useState(player.last_name);
  const [birthDate, setBirthDate] = useState(player.birth_date ?? "");
  const [position, setPosition] = useState(player.primary_position ?? "");
  const [foot, setFoot] = useState(player.preferred_foot ?? "");
  const [federationId, setFederationId] = useState(player.federation_id ?? "");
  const [status, setStatus] = useState(player.status);
  const [photoId, setPhotoId] = useState<string | null>(player.photo_media_id);
  const [photoUrl, setPhotoUrl] = useState<string | null>(player.photo_url);

  const [teamId, setTeamId] = useState(player.team?.id ?? "");
  const [shirt, setShirt] = useState(player.shirt_number?.toString() ?? "");
  const [seeded, setSeeded] = useState<string | null>(null);

  if (open && seeded !== player.id) {
    setSeeded(player.id);
    setFirstName(player.first_name);
    setLastName(player.last_name);
    setBirthDate(player.birth_date ?? "");
    setPosition(player.primary_position ?? "");
    setFoot(player.preferred_foot ?? "");
    setFederationId(player.federation_id ?? "");
    setStatus(player.status);
    setPhotoId(player.photo_media_id);
    setPhotoUrl(player.photo_url);
    setTeamId(player.team?.id ?? "");
    setShirt(player.shirt_number?.toString() ?? "");
  }
  if (!open && seeded !== null) setSeeded(null);

  /**
   * One save for the whole dialog.
   *
   * There were two — one per section — and the lower one is disabled until the
   * squad actually changes, so somebody who edited the photo and pressed the
   * Save nearest the bottom of a long dialog got nothing at all, with no
   * explanation. Two buttons with the same word, one of them inert, is a trap;
   * the sections are ours, not the user's.
   *
   * The squad move is still a separate call because it is a separate thing —
   * ending one registration and opening another — but the user should not have
   * to know that.
   */
  async function saveEverything() {
    await new Promise<void>((resolve) => {
      save.mutate(
        {
          id: player.id,
          changes: {
            first_name: firstName.trim(),
            last_name: lastName.trim(),
            birth_date: birthDate || null,
            primary_position: position || null,
            preferred_foot: foot || null,
            federation_id: federationId.trim() || null,
            photo_media_id: photoId,
            status,
          },
        },
        {
          onSuccess: () => resolve(),
          onError: (error) => {
            toast.error(error.message);
            resolve();
          },
        },
      );
    });

    if (!squadChanged) {
      toast.success(t("playerEdit", "saved"));
      return;
    }

    move.mutate(
      {
        id: player.id,
        change: {
          team_id: teamId || null,
          shirt_number: shirt ? Number(shirt) : null,
        },
      },
      {
        onSuccess: () => toast.success(t("playerEdit", "moved")),
        onError: (error) => toast.error(error.message),
      },
    );
  }

  const squadChanged =
    teamId !== (player.team?.id ?? "") ||
    shirt !== (player.shirt_number?.toString() ?? "");

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("playerEdit", "edit")}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            onClick={() => void saveEverything()}
            loading={save.isPending || move.isPending}
            disabled={!firstName.trim() || !lastName.trim()}
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        <section>
          <p className="text-sm font-medium text-text">{t("playerEdit", "details")}</p>
          <p className="mt-0.5 mb-4 text-xs text-text-secondary">
            {t("playerEdit", "detailsHint")}
          </p>

          <div className="grid gap-4 sm:grid-cols-[9rem_1fr]">
            <ImageField
              purpose="PLAYER_PHOTO"
              label={t("playerEdit", "photo")}
              help={t("playerEdit", "photoHint")}
              aspect="3/4"
              value={photoUrl}
              onChange={(asset) => {
                setPhotoId(asset?.id ?? null);
                setPhotoUrl(asset?.url ?? null);
              }}
            />
            <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("playerEdit", "firstName")} required>
              {(props) => (
                <Input
                  {...props}
                  value={firstName}
                  onChange={(event) => setFirstName(event.target.value)}
                />
              )}
            </Field>
            <Field label={t("playerEdit", "lastName")} required>
              {(props) => (
                <Input
                  {...props}
                  value={lastName}
                  onChange={(event) => setLastName(event.target.value)}
                />
              )}
            </Field>

            <Field label={t("playerEdit", "birthDate")}>
              {(props) => (
                <Input
                  {...props}
                  type="date"
                  value={birthDate}
                  onChange={(event) => setBirthDate(event.target.value)}
                />
              )}
            </Field>
            <Field label={t("playerEdit", "federationId")}>
              {(props) => (
                <Input
                  {...props}
                  value={federationId}
                  onChange={(event) => setFederationId(event.target.value)}
                />
              )}
            </Field>

            <Field label={t("playerEdit", "position")}>
              {(props) => (
                <Select
                  {...props}
                  value={position}
                  onChange={setPosition}
                  options={POSITIONS.map((value) => ({ value, label: value }))}
                />
              )}
            </Field>
            <Field label={t("playerEdit", "foot")}>
              {() => (
                <Segmented
                  value={foot || "RIGHT"}
                  onChange={setFoot}
                  ariaLabel={t("playerEdit", "foot")}
                  options={FEET.map((value) => ({
                    value,
                    label: t("playerEdit", `foot${value}` as "footLEFT"),
                  }))}
                />
              )}
            </Field>

            <Field label={t("playerEdit", "status")} className="sm:col-span-2">
              {(props) => (
                <Select
                  {...props}
                  value={status}
                  onChange={setStatus}
                  options={STATUSES.map((value) => ({
                    value,
                    label: t("playerEdit", `status${value}` as "statusTRIAL"),
                  }))}
                />
              )}
            </Field>
            </div>
          </div>

        </section>

        <Separator />

        <section>
          <p className="text-sm font-medium text-text">{t("playerEdit", "squad")}</p>
          <p className="mt-0.5 mb-4 text-xs text-text-secondary">
            {t("playerEdit", "squadHint")}
          </p>

          <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
            <Field label={t("playerEdit", "team")}>
              {(props) => (
                <Select
                  {...props}
                  value={teamId}
                  onChange={setTeamId}
                  placeholder={t("playerEdit", "noTeam")}
                  options={[
                    { value: "", label: t("playerEdit", "noTeam") },
                    ...(teams.data ?? []).map((team) => ({
                      value: team.id,
                      label: team.name,
                    })),
                  ]}
                />
              )}
            </Field>
            <Field label={t("playerEdit", "shirtNumber")}>
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={1}
                  max={99}
                  value={shirt}
                  disabled={!teamId}
                  onChange={(event) => setShirt(event.target.value)}
                />
              )}
            </Field>
          </div>

        </section>
      </div>
    </Dialog>
  );
}
