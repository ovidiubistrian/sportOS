import {
  ApiError,
  useAddMatchEvent,
  useUpdateMatch,
  type Match,
  type MatchEventInput,
} from "@footbola/api-client";
import { Badge, Button, Card, Field, Input, Select, useToast } from "@footbola/ui";
import { Plus } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../app/locale";

/**
 * What a club does from the stand while a match is on.
 *
 * Two jobs the league feed does badly, side by side.
 *
 * **Events, because the feed is late.** Checked against a live fixture: at
 * minute 34 the provider had the goal from 31 and none of the three yellow
 * cards actually shown. Goals arrive within a few minutes; cards arrive late
 * or not at all below the top divisions. So the buttons are one tap each and
 * the minute is pre-filled — somebody doing this in a crowd has one hand.
 *
 * **The round, because the feed is wrong.** A preliminary cup tie arrived
 * labelled "Final". The correction is stored separately from the provider's
 * own label, so the sync keeps writing underneath it and the fix survives.
 *
 * Everything entered here is marked as the club's, and the sync leaves it
 * alone rather than overwriting it when the feed catches up.
 */

const KINDS: { kind: MatchEventInput["kind"]; detail: string; labelKey: string }[] = [
  { kind: "GOAL", detail: "Normal Goal", labelKey: "eventGoal" },
  { kind: "CARD", detail: "Yellow Card", labelKey: "eventYellow" },
  { kind: "CARD", detail: "Red Card", labelKey: "eventRed" },
  { kind: "SUBSTITUTION", detail: "Substitution", labelKey: "eventSubstitution" },
];

export function MatchdayConsole({ match, clubId }: { match: Match; clubId: string }) {
  const { t } = useI18n();
  const toast = useToast();

  const addEvent = useAddMatchEvent(clubId);
  const updateMatch = useUpdateMatch(clubId);

  // Pre-filled from the clock the feed reports, so the common case is a tap.
  const [minute, setMinute] = useState(String(match.minute ?? ""));
  const [player, setPlayer] = useState("");
  const [side, setSide] = useState<"home" | "away">("home");
  const [round, setRound] = useState(match.round_label ?? "");

  const record = async (kind: MatchEventInput["kind"], detail: string) => {
    try {
      await addEvent.mutateAsync({
        matchId: match.id,
        event: {
          kind,
          detail,
          minute: minute ? Number(minute) : null,
          player_name: player.trim() || null,
          is_home: side === "home",
        },
      });
      // The name clears and the minute does not: the next thing to happen is
      // usually somebody else, at roughly the same time.
      setPlayer("");
      toast.success(t("matchday", "recorded"));
    } catch (error) {
      if (error instanceof ApiError) toast.error(error.message);
    }
  };

  const saveRound = async () => {
    try {
      await updateMatch.mutateAsync({
        id: match.id,
        changes: { round_label_override: round.trim() || null },
      });
      toast.success(t("matchday", "roundSaved"));
    } catch (error) {
      if (error instanceof ApiError) toast.error(error.message);
    }
  };

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-text">{t("matchday", "addEvent")}</p>
          {match.status === "LIVE" && (
            <Badge tone="danger" size="sm" dot>
              {t("matchday", "live")}
            </Badge>
          )}
        </div>
        <p className="mt-1 text-xs text-text-secondary">{t("matchday", "addEventHint")}</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-[90px_1fr_140px]">
          <Field label={t("matchday", "minute")}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={0}
                max={130}
                value={minute}
                onChange={(event) => setMinute(event.target.value)}
              />
            )}
          </Field>
          <Field label={t("matchday", "player")}>
            {(props) => (
              <Input
                {...props}
                value={player}
                onChange={(event) => setPlayer(event.target.value)}
                placeholder={t("matchday", "playerHint")}
              />
            )}
          </Field>
          <Field label={t("matchday", "forWhom")}>
            {() => (
              <Select
                value={side}
                onChange={(value) => setSide(value as "home" | "away")}
                options={[
                  { value: "home", label: match.home.name },
                  { value: "away", label: match.away.name },
                ]}
              />
            )}
          </Field>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {KINDS.map((entry) => (
            <Button
              key={`${entry.kind}-${entry.detail}`}
              variant="secondary"
              loading={addEvent.isPending}
              onClick={() => void record(entry.kind, entry.detail)}
            >
              <Plus className="size-4" />
              {t("matchday", entry.labelKey as "eventGoal")}
            </Button>
          ))}
        </div>
      </Card>

      <Card className="p-5">
        <p className="text-sm font-medium text-text">{t("matchday", "roundTitle")}</p>
        <p className="mt-1 text-xs text-text-secondary">{t("matchday", "roundHint")}</p>

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Field label={t("matchday", "roundLabel")} className="min-w-[220px] flex-1">
            {(props) => (
              <Input
                {...props}
                value={round}
                onChange={(event) => setRound(event.target.value)}
              />
            )}
          </Field>
          <Button variant="primary" loading={updateMatch.isPending} onClick={saveRound}>
            {t("common", "save")}
          </Button>
        </div>
      </Card>
    </div>
  );
}
