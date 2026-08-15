# 20 — The league feed (API-Football)

One platform-held key serves every club, exactly like the writing assistant.
The secret is environment-only (`API_FOOTBALL_KEY`); the super admin controls
policy, never the key. `GET /platform/api-football` reports `key_configured` as
a boolean and nothing else.

## The shared allowance

A shared key means a shared daily quota: a club syncing hourly spends the
allowance of one syncing nightly. Three consequences are built in.

* Nothing calls the provider while rendering a page. Sync is scheduled or
  triggered by hand from the console, so a club site stays up when the provider
  is down, slow or unpaid.
* Every run is recorded in `provider_sync_run` with its request count, so "who
  spent the quota" is answerable.
* Live scores never use the provider's `live=all`. On a Saturday that returns
  every match on the planet; instead the candidates are our own kicked-off,
  unfinished fixtures, looked up by id.

The client also reads `x-ratelimit-requests-remaining` and refuses to spend a
call it already knows will be rejected.

## Authority: the provider owns linked competitions

`match.source` is `CLUB` or `API_FOOTBALL`. Once the platform links a season,
sync writes those fixtures and the club can no longer edit or delete them — it
is told so in a sentence rather than having an edit silently reverted by the
next pull. Clubs keep entering everything the feed does not cover: friendlies,
youth fixtures, anything below the provider's coverage.

Unlinking hands them back. The matches stay — a season of results is not the
platform's to delete — and their source returns to `CLUB`.

## Two problems worth knowing about

**Adoption.** A club that has been keeping its calendar by hand has fixtures
with no provider id. Creating rows for the provider's copies would double every
match in the season and count each result twice in the table. `_adopt` matches
an unlinked fixture between the same two clubs within a week of the provider's
date and takes it over. Club rows are likewise matched by slug when the
provider id is new, so switching the feed on does not create a second
"CSM Reșița".

**Live scores needed the check constraint widened.** `match_score_matches_status`
required a score exactly when the status was FINISHED or AWARDED. A kicked-off
match has a score from the first minute, so LIVE now belongs in that set — and
the provider sometimes sends null goals at kick-off, which the sync coerces to
nil-nil rather than writing a row the database will reject.

## Getting a key

Sign up at <https://dashboard.api-football.com>, then put the key in `.env` as
`API_FOOTBALL_KEY` and restart the API. Until then every sync fails with
"No API-Football key is configured on this platform" — deliberately a sentence,
not a 500.

Linking is per season: `POST /platform/api-football/links` with our
`competition_season_id` and the provider's league id and year. Romania's Liga 2
is league 284; the provider's `/leagues` endpoint lists the rest.

## Match events

`match_event` holds goals, cards and substitutions — global, like the match
itself, because two clubs play one game and each keeping its own copy would
give it two scorers.

Player names are text, not a foreign key to `player`. The scorer is usually
somebody else's player, who this platform has no row for and never will, and a
goal that could not be recorded because the scorer is not a customer would be
an absurd rule.

The provider's dozen event types collapse to four — GOAL, CARD, SUBSTITUTION,
VAR — because a match report listing every kind of VAR check is a log rather
than a story. Its `detail` string is kept verbatim, since it is the only thing
separating a penalty from a header, and translated at the edge.

Events are fetched one call per match and only where it is worth spending one:
a fixture that has not kicked off has none, and a finished match's events do
not change once the referee has gone home, so they are read once. A live match
is refreshed while it is on.

## History and palmarès

`club_season_record` holds where a club finished, one season per row: position,
record, points and the provider's own description of the outcome ("Promotion
Group", "Relegation Round"). That last field matters — finishing fourth means
promotion in one division and nothing in another, and only the competition
knows which.

Stored rather than computed. A finished season's table is a fact that will not
change, and recomputing it would mean holding every fixture the club ever
played to answer "how did we do in 2021?".

**There is no honours endpoint.** `/trophies` exists for players and coaches
but rejects a team id outright. So the palmarès is *derived*: a title is a
first place in a table we have, not a claim somebody typed into a form. An
empty honours section that fills itself the season a club wins something is
better than a list nobody can check.

The sync is deliberately not on a timer. One call lists every competition and
season the club has played; one more per league season fetches the table, cups
skipped because they have no standings. Seasons already recorded are not
re-read. A club pulls its history when it connects the feed, and again if it
wants to — nightly would spend a dozen calls to rewrite identical rows.

`/teams?id=` also gives the founding year, ground and capacity, which is where
the club page's facts come from.
