# 17 — Newsroom and the writing assistant

How a club publishes news, and how the assistant helps without taking the pen
out of the editor's hand.

---

## 1. One article, many languages

A tenant declares `supported_locales`. An article is therefore two things:

- **`content_item`** — the lifecycle. Status, schedule, pin, article type, club.
- **`content_translation`** — the words, one row per language.

Splitting them is what makes *"live in Romanian, still being translated into
German"* a state the system can hold and the editor can see. If language lived on
the item, a club would have to publish two half-articles and keep them in step by
hand.

Two constraints follow from that, and both are in the database rather than in
service code:

```sql
CHECK (status <> 'SCHEDULED' OR scheduled_for IS NOT NULL)
CHECK (status <> 'PUBLISHED' OR published_at IS NOT NULL)
```

A scheduled article with no date would never publish; a published article with no
date could not be ordered. Neither is representable.

Slugs are unique per `(club, locale)`, so `/news/echipa-noastra` and
`/news/our-team` are the same article in two languages.

## 2. Bodies are blocks, not HTML

A body is a list of typed blocks — `paragraph`, `heading`, `quote`, `list`. Two
reasons, and the second is the important one:

1. **Four templates, one body.** Each site template renders a quote in its own
   character. An HTML blob would force every template to look the same, or to
   parse and re-style someone else's markup.
2. **Stored XSS is unrepresentable.** Blocks carry text; the templates render
   text nodes. There is no path from stored content to executable markup, so
   there is nothing to sanitise and nothing to get wrong later.

The block set is deliberately small. A club publishes match reports and
announcements; it does not build landing pages.

## 3. Article types

A club newsroom writes the same handful of things: a match report, a signing, a
departure, a fixture preview. Naming those types buys three things at once:

- a **starter skeleton**, so an editor faces a structure rather than a blank page
  — with placeholder text that prompts (*"What they gave the club: years,
  appearances, moments"*) rather than lorem, so a skeleton can never be published
  by accident and read as finished copy;
- **context for the assistant** — *"polish this"* is a far better instruction when
  the model knows it is polishing a farewell to a departing player rather than a
  cup draw;
- **structure for the newsroom** — the admin list filters by type, and the
  question *"show me every departure we've published"* has an answer.

Types are a closed set (`app/cms/article_types.py`), like site templates: a club
picks one, it cannot invent one, because every type carries prompt and layout
behaviour that has to exist. Each type also declares `protected_facts` — the
numbers that would force the club to publish a correction if invented. For a
signing that is the fee, contract length, previous club and age; for a match
report the scoreline, scorers and attendance.

## 4. The writing assistant

Full rationale in [ADR-0011](../decisions/ADR-0011-ai-writing-assistant.md). The
shape of it:

```
POST /api/v1/ai/polish      → a suggested body + one sentence on what changed
POST /api/v1/ai/headlines   → three to five alternatives
GET  /api/v1/ai/assistant   → available? why not? how much allowance is left?
```

**No endpoint writes to an article.** `polish` returns a proposal; the editor
reads it side by side with their own text, with changed blocks highlighted, and
accepts or discards. Accepting goes through the normal content update route. The
choice is recorded (`ai_usage.accepted`) because whether editors keep the
suggestions is the only honest measure of whether the feature earns its cost.

**One key, held by the platform.** Read from the environment; never stored in the
database, never settable from an admin screen. What the super admin controls is
the policy: `ai_assist` (on/off) and `ai_requests_per_month` (how much), written
as entitlement overrides with a mandatory reason, through a step-up-authenticated
endpoint.

**Guardrails, in order of how much they matter:**

| Guard | Where |
| --- | --- |
| "Never introduce a fact that is not in the draft" — the first rule of the prompt | `app/ai/prompts.py` |
| Per-type protected facts named explicitly in the prompt | `app/cms/article_types.py` |
| Quotes are never reworded — only the prose around them | `BASE_RULES` |
| Output constrained to our four block types, `additionalProperties: false` | `BLOCK_SCHEMA` |
| Returned blocks re-validated through the CMS models before display | `app/ai/service.py` |
| `stop_reason == "refusal"` checked before any content is read | `app/ai/provider.py` |
| Draft size bounded before the call, so a paste cannot become a large bill | `app/ai/service.py` |

The usage ledger records who asked, when, and what it cost — and deliberately
**no prompt text and no article content**. An unannounced signing is a story the
club owns, and a metering table is the wrong place for it to live.

## 5. Where the code sits

| Path | What |
| --- | --- |
| `app/cms/` | Items, translations, the state machine, blocks, the scheduler, article types |
| `app/ai/` | Provider port and Anthropic adapter, prompts, the assistant service, usage ledger |
| `app/platform/ai_router.py` | Cross-tenant cost console and the per-tenant policy switch |
| `apps/admin-web/src/pages/news/` | The newsroom list, the editor, the block editor, the assistant panel |

`app/ai` is a tier-3 support module for `cms` and never reaches beyond one
tenant. Anything cross-tenant is `platform`, tier 5 — see
[02 — Domain boundaries](02-domain-boundaries.md).
