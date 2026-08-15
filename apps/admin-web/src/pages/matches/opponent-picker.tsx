import { useAddDirectoryClub, useDirectoryClubs, type DirectoryClub } from "@footbola/api-client";
import { Button, Input, Spinner, cn } from "@footbola/ui";
import { Check, Plus, Search } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";

/**
 * Choosing who you play.
 *
 * A plain select would do if every opponent were already on the platform, but
 * most are not: a Liga 2 club plays fifteen sides that have never heard of us.
 * So this searches the shared directory and, when nothing matches, offers to
 * add the name — which is the difference between a club being able to enter its
 * own season and having to wait for us to seed it.
 *
 * The list is scoped to the season when there is one, so the clubs in your
 * division come first and typing is only needed for the rest.
 */
export function OpponentPicker({
  seasonId,
  value,
  onChange,
}: {
  seasonId: string | null;
  value: DirectoryClub | null;
  onChange: (club: DirectoryClub) => void;
}) {
  const { t } = useI18n();
  const { club } = useSession();
  const [search, setSearch] = useState("");
  // Widen past the season's entrants once the user starts typing: they are
  // looking for someone who is not in the division list.
  const clubs = useDirectoryClubs(search.trim() ? null : seasonId, search);
  const add = useAddDirectoryClub();

  // Your own club is in the division too, and the API refuses a fixture against
  // yourself — so offering it is a dead end with an error at the end of it.
  const results = (clubs.data ?? []).filter(
    (row) => row.id !== club.directory_club_id,
  );
  const typed = search.trim();
  const exact = results.some((club) => club.name.toLowerCase() === typed.toLowerCase());

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-tertiary" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("matches", "opponentSearch")}
          className="pl-9"
        />
      </div>

      <div className="max-h-56 overflow-y-auto rounded-md border border-border">
        {clubs.isLoading ? (
          <div className="grid h-20 place-items-center">
            <Spinner />
          </div>
        ) : (
          <ul>
            {results.map((club) => (
              <li key={club.id}>
                <button
                  type="button"
                  onClick={() => onChange(club)}
                  className={cn(
                    "flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm",
                    "transition-colors hover:bg-surface-sunken",
                    value?.id === club.id && "bg-brand-subtle text-brand-text",
                  )}
                >
                  {club.crest_url ? (
                    <img src={club.crest_url} alt="" className="size-5 object-contain" />
                  ) : (
                    <span className="grid size-5 place-items-center rounded bg-surface-sunken text-[9px] font-bold text-text-tertiary">
                      {club.short_name.slice(0, 3)}
                    </span>
                  )}
                  <span className="flex-1 truncate">{club.name}</span>
                  {value?.id === club.id && <Check className="size-4" />}
                </button>
              </li>
            ))}

            {typed.length >= 2 && !exact && (
              <li className="border-t border-border p-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  loading={add.isPending}
                  onClick={() => {
                    add.mutate(
                      { name: typed },
                      {
                        onSuccess: (club) => {
                          onChange(club);
                          setSearch("");
                        },
                      },
                    );
                  }}
                >
                  <Plus className="size-4" />
                  {t("matches", "opponentMissing", { name: typed })}
                </Button>
              </li>
            )}
          </ul>
        )}
      </div>

      {value && (
        <p className="text-xs text-text-secondary">
          {t("matches", "opponent")}: <span className="font-medium text-text">{value.name}</span>
        </p>
      )}
    </div>
  );
}
