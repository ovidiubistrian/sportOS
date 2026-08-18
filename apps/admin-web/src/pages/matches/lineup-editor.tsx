import {
  ApiError,
  useArrangeLineup,
  useMatchLineups,
  type LineupSheet,
  type LineupSheetPlayer,
} from "@footbola/api-client";
import { Badge, Button, Card, Segmented, Select, Skeleton, useToast } from "@footbola/ui";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "../../app/locale";

/**
 * Putting the eleven on the pitch.
 *
 * The provider gives names and shirt numbers for every league and positions
 * only for the ones it covers fully — not the Romanian second division — so
 * for most clubs this is where a formation comes from at all.
 *
 * **Tap a shirt, tap a slot.** Not drag-and-drop: this is used on a phone, an
 * hour before kick-off, by somebody who may be standing up. Dragging on a
 * touch screen fights the page's own scrolling, and a mis-drag loses the
 * placement silently. Two taps cannot be half-done.
 *
 * The formation drives the slots and nothing else. Changing it keeps whoever
 * still fits and drops the rest back to the bench, rather than clearing the
 * board — moving from 4-4-2 to 4-2-3-1 should not cost the ten players who did
 * not move.
 */

const FORMATIONS = [
  "4-4-2",
  "4-3-3",
  "4-2-3-1",
  "3-5-2",
  "3-4-3",
  "5-3-2",
  "4-1-4-1",
  "4-5-1",
];

/** Rows of slots, goalkeeper first, from a formation like "4-2-3-1". */
function slotsFor(formation: string): string[][] {
  const bands = formation
    .split("-")
    .map((part) => Number(part.trim()))
    .filter((count) => Number.isFinite(count) && count > 0);

  // Row 1 is always the goalkeeper — the provider's own convention, and the
  // reason a formation names ten players rather than eleven.
  const rows: string[][] = [["1:1"]];
  bands.forEach((count, band) => {
    rows.push(
      Array.from({ length: count }, (_, index) => `${band + 2}:${index + 1}`),
    );
  });
  return rows;
}

export function LineupEditor({
  matchId,
  clubId,
  homeName,
  awayName,
}: {
  matchId: string;
  clubId: string;
  homeName: string;
  awayName: string;
}) {
  const { t } = useI18n();
  const toast = useToast();

  const sheets = useMatchLineups(matchId, clubId);
  const arrange = useArrangeLineup(clubId);

  const [side, setSide] = useState<"HOME" | "AWAY">("HOME");
  const [formation, setFormation] = useState("4-4-2");
  const [placed, setPlaced] = useState<Record<string, string>>({});
  const [holding, setHolding] = useState<string | null>(null);

  const sheet: LineupSheet | undefined = sheets.data?.find((row) => row.side === side);

  // Load what is stored whenever the side changes, so switching between teams
  // does not carry one team's arrangement onto the other.
  useEffect(() => {
    if (!sheet) return;
    setFormation(sheet.formation ?? "4-4-2");
    const next: Record<string, string> = {};
    for (const player of sheet.starters) {
      if (player.grid) next[player.grid] = player.name;
    }
    setPlaced(next);
    setHolding(null);
  }, [sheet]);

  const rows = useMemo(() => slotsFor(formation), [formation]);
  const validSlots = useMemo(() => new Set(rows.flat()), [rows]);

  // A slot that no longer exists in this formation drops its player back to
  // the bench rather than keeping them somewhere invisible.
  const effective = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [slot, name] of Object.entries(placed)) {
      if (validSlots.has(slot)) out[slot] = name;
    }
    return out;
  }, [placed, validSlots]);

  const taken = new Set(Object.values(effective));
  const bench = (sheet?.starters ?? []).filter((player) => !taken.has(player.name));

  const place = (slot: string) => {
    if (!holding) {
      // Tapping an occupied slot picks that player up again.
      const sitting = effective[slot];
      if (sitting) {
        setPlaced((current) => {
          const next = { ...current };
          delete next[slot];
          return next;
        });
        setHolding(sitting);
      }
      return;
    }
    setPlaced((current) => {
      const next = { ...current };
      // One player, one square: clear wherever they were standing before.
      for (const [key, name] of Object.entries(next)) {
        if (name === holding) delete next[key];
      }
      next[slot] = holding;
      return next;
    });
    setHolding(null);
  };

  const save = async () => {
    try {
      await arrange.mutateAsync({
        matchId,
        side,
        arrangement: {
          formation,
          positions: Object.entries(effective).map(([grid, name]) => ({ name, grid })),
        },
      });
      toast.success(t("matchday", "lineupSaved"));
    } catch (error) {
      if (error instanceof ApiError) toast.error(error.message);
    }
  };

  if (sheets.isLoading) return <Skeleton className="h-72" />;

  if (!sheets.data?.length) {
    return (
      <Card className="p-5">
        <p className="text-sm font-medium text-text">{t("matchday", "lineupTitle")}</p>
        <p className="mt-1 text-xs text-text-secondary">{t("matchday", "lineupWaiting")}</p>
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm font-medium text-text">{t("matchday", "lineupTitle")}</p>
        <Segmented
          ariaLabel={t("matchday", "lineupTitle")}
          value={side}
          onChange={(value) => setSide(value as "HOME" | "AWAY")}
          options={[
            { value: "HOME", label: homeName },
            { value: "AWAY", label: awayName },
          ]}
        />
        <Select
          value={formation}
          onChange={setFormation}
          options={FORMATIONS.map((value) => ({ value, label: value }))}
        />
        <Button
          variant="primary"
          className="ml-auto"
          loading={arrange.isPending}
          onClick={save}
        >
          {t("common", "save")}
        </Button>
      </div>

      {!sheet ? (
        <p className="mt-4 text-sm text-text-tertiary">{t("matchday", "lineupWaiting")}</p>
      ) : (
        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_220px]">
          {/* The pitch. Goalkeeper at the bottom, attack at the top, the way a
              team sheet is drawn on paper. */}
          <div className="rounded-xl bg-emerald-600/10 p-4">
            <div className="flex flex-col-reverse gap-3">
              {rows.map((slots, index) => (
                <div key={index} className="flex justify-center gap-2">
                  {slots.map((slot) => {
                    const name = effective[slot];
                    return (
                      <button
                        key={slot}
                        type="button"
                        onClick={() => place(slot)}
                        aria-label={name ?? t("matchday", "emptySlot")}
                        className={[
                          "h-14 min-w-[74px] flex-1 rounded-lg border px-1 text-[11px] leading-tight transition-colors",
                          name
                            ? "border-emerald-700 bg-emerald-700 text-white"
                            : holding
                              ? "border-dashed border-emerald-700 bg-surface hover:bg-emerald-50"
                              : "border-dashed border-border bg-surface",
                        ].join(" ")}
                      >
                        {name ? (
                          <span className="line-clamp-2">{name}</span>
                        ) : (
                          <span className="text-text-tertiary">+</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-text">
              {holding ? t("matchday", "tapASlot") : t("matchday", "tapAPlayer")}
            </p>
            <ul className="mt-2 space-y-1">
              {bench.map((player: LineupSheetPlayer) => (
                <li key={player.name}>
                  <button
                    type="button"
                    onClick={() => setHolding(player.name)}
                    className={[
                      "flex w-full items-baseline gap-2 rounded-lg px-2 py-1.5 text-left text-sm",
                      holding === player.name
                        ? "bg-accent-soft ring-1 ring-accent"
                        : "hover:bg-surface-2",
                    ].join(" ")}
                  >
                    <span className="w-5 text-right text-xs tabular-nums text-text-tertiary">
                      {player.shirt_number ?? ""}
                    </span>
                    <span className="min-w-0 truncate">{player.name}</span>
                  </button>
                </li>
              ))}
              {bench.length === 0 && (
                <li className="px-2 py-1.5 text-xs text-text-tertiary">
                  {t("matchday", "everyonePlaced")}
                </li>
              )}
            </ul>

            {sheet.source === "CLUB" && (
              <Badge tone="outline" size="sm" className="mt-3">
                {t("matchday", "arrangedByClub")}
              </Badge>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
