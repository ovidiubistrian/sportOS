# 18 — Languages and countries

The platform ships English and Romanian. Adding a third is a small, bounded
change — this document is what makes that true and keeps it true.

---

## 1. Two different things called "language"

They are configured separately because they answer different questions, and a
club routinely wants different answers.

| | **Interface language** | **Content languages** |
| --- | --- | --- |
| Question | What language does the admin appear in? | What languages does the club publish in? |
| Stored on | `tenant.default_locale` | `tenant.supported_locales` |
| Cardinality | One | One or more |
| Overridable | Yes, per user | No — it is a club decision |
| Who it serves | Staff | Supporters |

A Romanian academy with a German partner club runs its admin in Romanian and
publishes in `ro`, `en` and `de`. Collapsing these into one setting forces it to
choose which of those two facts to get wrong.

**The interface language is overridable per person** (stored locally, not on the
server) because a club can have one member of staff who does not speak the
club's language. **Content languages are not**, because what the website
publishes is a club decision, not a personal preference.

## 2. One registry, two halves, one test

| Half | Where | What it holds |
| --- | --- | --- |
| Backend | `app/core/locales.py` | The codes a tenant may be configured with |
| Frontend | `packages/i18n/src/` | The words for each of those codes |

Neither half is authoritative on its own, and that is the risk: a locale the
backend accepts but the frontend cannot render produces an admin with English
words scattered through it, reported weeks later as "the translation is broken".

So the agreement is a test rather than a convention —
`backend/tests/i18n/test_locales.py` fails if:

- the two lists of codes differ;
- a supported locale has no catalogue file;
- a catalogue is missing a key English has, or has one English does not.

The frontend's own type checker proves the same thing more strictly (`Catalogue`
is the shape of the English catalogue with its leaves widened to `string`, so a
missing key is a compile error). The backend test exists so the failure also
appears for someone who is not running `tsc`.

## 3. Adding a language

Three edits and a translation pass.

1. **`backend/app/core/locales.py`** — add a `Locale(code, endonym, english_name)`.
   The endonym is written in the language itself: a speaker scans for the word
   *they* use for their language, not for its English name.
2. **`packages/i18n/src/index.ts`** — add the same code to `LOCALES`.
3. **`packages/i18n/src/<code>.ts`** — copy `catalogue.ts`, type it as
   `Catalogue`, translate. The type checker lists anything you missed.

Then run the suite. Nothing else changes: the admin, the command palette's
keyword matching, plural selection, and date and number formatting all read from
the registry.

**Existing tenants keep the languages they have.** A new locale becomes
*available*, not applied — nobody's interface changes language because the
platform learned a new one.

### What is deliberately not part of adding a language

- **No string extraction step.** Messages live in the catalogue from the moment
  they are written. A codebase where translation is a later pass accumulates
  hardcoded English until the pass is too big to do.
- **No runtime message compilation.** Interpolation is `{name}` and nothing
  else. A translator should never have to read code, and the admin should not
  wait on a formatting library before its first paint.
- **Plurals are separate keys** (`_one` / `_other`), selected by `Intl.PluralRules`
  for the active locale. Romanian's three-way rule works without the English
  catalogue knowing that Romanian has one.

## 4. Countries are not languages

A country decides *money, time and law*. A language decides *words*. They vary
independently — Romanian is spoken in Romania and Moldova, and a club in either
may bill in EUR or RON.

So they are separate fields on the tenant, and region subtags fold away:
`ro-RO`, `ro-MD` and `ro` all resolve to Romanian.

| Concern | Where it lives | Notes |
| --- | --- | --- |
| Currency | `tenant.default_currency` | ISO 4217, with a per-currency minor-unit exponent — see `app/core/money.py`. Never assume two decimals. |
| Timezone | `tenant.timezone` | IANA. Kick-off times are meaningless without it. |
| Country | `tenant.country_code` | ISO 3166-1 alpha-2. Drives VAT and federation rules as those arrive. |
| Date and number format | Derived from the interface locale | `Intl`, never hand-rolled. |

Nothing in the product branches on country today. When something must — VAT
rates, federation registration rules, safeguarding requirements — it belongs
behind a per-country policy object, resolved from `country_code`, in the module
that needs it. Not in a conditional inside a form.

## 5. The public site

A club site is served in a **content** language, chosen by the reader and
falling back to the tenant's default when an article has not been translated
yet. That is separate from the interface language: a supporter reading a
Romanian club's English page never touches the admin.

When a fallback happens the page says so, rather than silently serving an
unexpected language — see `served_locale_fallback` in the public article schema.

## Competitions in the admin

A club runs its own season from `/:clubSlug/matches`: it enters a competition,
adds fixtures, and records results. Three points are worth stating because they
are not obvious from the schema.

**Playing in a season is what being in it means.** Adding a fixture enters both
clubs into that season's entry list. Before this, an opponent added by name
stayed outside the list, `compute_table` skipped every result against them as a
data error, and the club recorded a season of scores into nothing.

**The opponent directory is find-or-create by slug.** Two clubs in the same
division will both add the same opponent; the second is not making a mistake.
Returning the existing row is what keeps their fixtures pointing at one club
rather than two spellings of it.

**Fixtures purge the public site.** `MatchScheduleChanged` carries the club, not
the match, because the site renders a whole fixture list and a whole table — one
result invalidates both. It shares `_purge` with branding and content changes;
the resolve and the purge run in one transaction, so a retry after a failed
purge cannot be told the event is already handled and give up.

Tests live in `backend/tests/competitions/test_matches.py`. They enter a season
named for the run rather than the real one: competitions are shared platform
data, and a test that joined 2025/26 would leave its throwaway opponents in the
table a real club shows on its website.

## The club front page

The order is fixed in `app/(club)/page.tsx`, not in the templates, because it is
the club's reading of its own week rather than a design choice:

1. **News carousel** — the club's own words and pictures, largest first. The one
   client component on the site; everything under it stays server-rendered.
2. **The next match**, with the message the club wrote in admin above it. One
   fixture, not four: a club has something to say about the match it is about to
   play.
3. **The rest of the run**, then the table.

The squad list is not on the front page. It is a reference page (`/teams`), and
a supporter checking a kick-off time should not scroll past six age groups to
reach it. Each template exports `Squads` for that route.

Articles carry `cover_media_id` — on the item, not the translation, because a
photograph of a signing is the same photograph in every language. Without a
cover the carousel falls back to the club's hero image, so a club that has not
uploaded anything still gets a hero rather than a gap.

`ClubBrandingChanged` also syncs the club's crest onto its `directory_club` row.
The two rows are separate by design — one is the tenant's, one is the platform's
— but a club that uploads its badge expects to see it in its own fixture list
and its own table, and nothing else was going to put it there.

## Editing squads

`PATCH /teams/{id}` renames and archives; there is no delete, because a season of
registrations and results hangs off a team. `GET /teams` returns only active
ones, so archiving is what "remove" means from the club's side.

`PUT /players/{id}/registration` moves a player between squads. It ends the
current registration and opens another rather than updating a row — "which team
was he in last March?" has to stay answerable, and an UPDATE erases the answer.
`tests/teams/test_squad_editing.py` reads the table directly to assert this,
since the API only ever shows the live registration and so cannot tell an ended
row from an overwritten one.

Fixtures, by contrast, *are* deletable (`DELETE /matches/{id}`, scheduled ones
only): a fixture entered by mistake never happened, and hiding it would still
count it toward its season.
