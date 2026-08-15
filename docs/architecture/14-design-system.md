# 14 — Design System Foundations

## 1. Design intent

Three surfaces, three jobs. They share tokens and primitives; they do not share
personality.

| Surface | Character | Optimised for |
| --- | --- | --- |
| `admin-web` / `super-admin` | Neutral, dense, quiet | Operational efficiency. The UI should disappear. |
| `public-web` | Expressive, club-branded, image-led | Emotion, identity, conversion |
| `scanner` | Extreme, high-contrast, single-purpose | One decision, readable at arm's length in rain |

The reference points for admin are Linear and the Stripe Dashboard: strong
typographic hierarchy, restrained colour, high information density, no
decoration that does not carry information. Not their branding — their
*discipline*.

Explicitly rejected: gradient headers, glassmorphism, neon accents, oversized
radii, drop shadows on everything, dashboards made of unrelated stat cards,
emoji as iconography, and full-width hero sections in an admin tool.

## 2. Tokens

Tokens are CSS custom properties, exposed through a Tailwind v4 preset in
`packages/config`. Components consume tokens, never raw values.

### Spacing — 4 px base

```
space-1  4px    space-2  8px    space-3  12px   space-4  16px
space-6  24px   space-8  32px   space-12 48px   space-16 64px
```

### Radius

```
radius-sm  6px     inputs, buttons, badges
radius-md  8px     cards, popovers, menus
radius-lg  12px    modals, sheets
radius-full        avatars, pills only
```

Nothing is more rounded than 12 px except pills. Large radii read as consumer-app
playfulness and undermine the operational tone.

### Typography — Inter (variable), `ui-monospace` for numerics

```
text-xs    12 / 16   labels, table meta, captions
text-sm    13 / 20   table body, secondary text          ← admin default
text-base  14 / 22   body, form inputs
text-lg    16 / 24   section headings
text-xl    20 / 28   page titles
text-2xl   24 / 32   dashboard figures
text-3xl   30 / 38   public-web headings only
```

13 px table body is deliberate. At 14 px a supporter list shows ~18 rows on a
laptop; at 13 px it shows ~24. For someone reconciling 900 season tickets that
difference is the product.

**Tabular numerals** (`font-variant-numeric: tabular-nums`) on every number in a
table, every price, every count. Non-aligned digits in a financial column is the
fastest way to look amateur.

### Colour

Two families, kept strictly apart:

**Neutral (the interface)** — a 12-step slate ramp, identical in every tenant.

```
--bg            --bg-subtle      --bg-muted
--surface       --surface-raised --surface-overlay
--border        --border-strong
--text          --text-secondary --text-tertiary --text-disabled
```

**Semantic (state)** — fixed, never club-branded, because meaning must be
constant across tenants:

```
--success  emerald    confirmed, paid, present, valid
--warning  amber      expiring, pending, already-used
--danger   red        failed, revoked, absent, destructive
--info     blue       informational
```

**Brand (identity)** — `--brand`, `--brand-contrast`, `--brand-subtle`, injected
per club at runtime.

> **Brand colour rule.** The club colour is used for: the primary action button,
> active navigation state, focus rings, links, and public-site accents. It is
> **not** used for table headers, backgrounds, borders, status indicators, chart
> series, or large fills. A club with a yellow brand colour and a club with a
> navy one must produce equally legible, equally professional interfaces. This
> single rule is what separates a white-label platform from a customisable theme.

Every brand colour is contrast-checked on upload. If `--brand` fails 4.5:1
against white, we derive an accessible `--brand-text` variant automatically and
use it for text, keeping the true colour for fills. The club sees its colour; the
user can read the page.

Dark mode is a first-class token set for admin and scanner (stewards work at
night; ticketing staff work long shifts). `public-web` follows the club's
choice — some clubs will not want a dark site.

### Elevation

```
shadow-sm   dropdowns, popovers
shadow-md   modals, sheets
```

Two shadows. Cards get a border, not a shadow. Shadow indicates *floating above
the page*, which a card does not do.

## 3. Component layers

```
packages/ui/
├── tokens/        CSS custom properties, Tailwind preset
├── primitives/    Button Input Select Checkbox Radio Switch Textarea
│                  Dialog Sheet Popover Tooltip DropdownMenu Tabs
│                  Badge Avatar Separator Skeleton Toast Command
├── patterns/      DataTable  PageHeader  FilterBar  EmptyState  ErrorState
│                  ConfirmDialog  FormField  StatGroup  Timeline
│                  DetailPanel  BulkActionBar  DateRangePicker  MoneyInput
└── charts/        Recharts wrappers with a fixed, accessible categorical palette
```

Primitives wrap Radix and add tokens + `cva` variants. Patterns compose
primitives into the shapes that repeat across the product. A screen should be
assembled almost entirely from patterns; if a screen needs a new primitive, that
is a design-system change with a review, not a local file.

### `DataTable` — the most important component

Every list screen in the product uses it. It owns: server-side sort/filter/page,
column visibility and order (persisted per user), density toggle, row selection
with a bulk-action bar, sticky header, sticky first column, keyboard navigation,
row actions in an overflow menu, saved views, CSV/XLSX export, loading skeletons
that match the real row height, and a proper empty state.

Building this once, well, is what makes 40 list screens consistent and cheap.
Building it 40 times is what makes a product feel generated.

## 3b. Public site templates

A club picks one of four templates and up to three colours. That is the whole
customisation surface: no custom CSS, no per-component overrides. The four are a
closed set in code (`apps/public-web/src/templates/`), sharing one content model,
one set of routes and one data layer — a template changes layout, density and
emphasis, never what the site contains.

| Template | Character | Suits |
| --- | --- | --- |
| **Classic** | Centred crest, formal masthead, bordered blocks, squads as tables | A club whose identity is its history; looks right with no photography |
| **Bold** | Full-bleed brand-colour hero, very large tight type, filled cards | A club with a strong visual identity |
| **Compact** | Narrow, dense, sidebar nav, no hero | Academies with many teams and few images, on poor connections |
| **Editorial** | Asymmetric magazine grid, hairline rules, numbered team index | Clubs that publish regularly |

Colours are supplied by the club and **never rejected**. The API derives, per
colour: `--brand-contrast` (black or white, whichever is readable on a fill of
it), `--brand-text` (the colour darkened until it passes AA as body text on
white) and a dark-surface equivalent. That derivation is why the Bold template
can safely use the brand colour as a full-bleed surface for any club — a yellow
club and a navy club both get legible hero text. See
`backend/app/tenants/colors.py` and its tests.

Adding a template means adding a module and one registry entry. Routes, data
fetching and the API are untouched — which is what stops "four styles" becoming
four codebases.

## 4. Screen patterns

**List page**: page header with title, count and one primary action → filter bar
(with saved views) → table → pagination. No stat cards above the table unless
they are *filters* the user actually clicks.

**Detail page**: header with identity, status badge and primary action →
tabs for sub-resources → two-column layout with the record on the left and
metadata/activity on the right.

**Form**: single column, max 640 px, logical grouping with section headings,
labels above inputs, help text below, errors attached to the field. Sticky
footer with Cancel / Save when the form is longer than the viewport. Never a
two-column form — it doubles error-scanning cost for no benefit.

**Dashboard**: not a wall of widgets. The club admin dashboard answers three
questions in this order:

```
TODAY                    what is happening in the next 24 hours
REQUIRES ATTENTION       what is blocked, expiring, unpaid, or failing — each
                         row links directly to the thing that fixes it
AT A GLANCE              a small number of figures with trend, no gauges
```

"Requires attention" is the section that makes the product valuable daily. Every
item in it is actionable and links to the resolution — an alert you cannot act on
is noise, and noise trains people to ignore the dashboard.

## 5. Mandatory states

Every data-bound component implements all five. This is a review checklist item,
not a suggestion:

| State | Requirement |
| --- | --- |
| Loading | Skeleton matching final layout dimensions. No spinners on full pages, no layout shift. |
| Empty (no data yet) | Explains what this is, and offers the action that creates the first one |
| Empty (no results) | Different from above: says which filters excluded everything, offers to clear them |
| Error | What failed, the `request_id`, and a retry. Never a raw error string. |
| Partial / degraded | Stale data marked as stale rather than silently shown as current |

## 6. Density and scale

Every screen is designed and reviewed at **5, 500 and 50 000 records**. The
review questions:

- 5 → does it look intentional, or broken and empty?
- 500 → do filters, sort and pagination genuinely work, or is it "load all"?
- 50 000 → does the page still render in under a second? Is the count estimated?
  Is bulk selection scoped to the filter rather than to loaded rows?

"Select all" on a filtered list must mean *all matching rows*, not *the 50 loaded
rows*. Getting this wrong turns a bulk email into an incident.

## 7. Motion

- 120 ms for hovers and focus, 180 ms for popovers and menus, 240 ms for sheets
  and modals. `ease-out` entering, `ease-in` leaving.
- Nothing animates on data load except skeleton shimmer.
- No parallax, no scroll-triggered reveals, no animated numbers in admin.
- `prefers-reduced-motion` removes all non-essential motion. Respected, not
  approximated.

## 8. Governance

- Figma is not the source of truth; `packages/ui` is. Design tokens are exported
  from code to Figma, not the reverse.
- Storybook for every primitive and pattern, with all five states rendered.
- Visual regression on the Storybook set (Playwright screenshots) so a token
  change surfaces everywhere it lands.
- Adding a colour, spacing value, radius or font size outside the token set fails
  a Tailwind lint rule. Arbitrary values (`p-[13px]`, `text-[#ff0000]`) are
  blocked.
- New patterns require a second reviewer from the design-system owners.

The constraint is the product. A design system nobody can bypass is what makes
sixty screens built by four engineers over two years look like one thing.
