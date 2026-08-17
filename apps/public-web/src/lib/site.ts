import { headers } from "next/headers";
import { cache } from "react";

/**
 * Club resolution.
 *
 * One deployment serves every club site. The club is resolved from the Host
 * header on each request — an unknown host 404s and never falls back to a
 * default club, because serving one club's content on another's domain is the
 * worst failure this app can have.
 *
 * Calls go to the API over the internal network. The browser never talks to
 * the API for public pages, so a club site works with no CORS configuration
 * and no public API surface.
 */

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

export type SiteTemplate = "CLASSIC" | "BOLD" | "COMPACT" | "EDITORIAL";

export interface Branding {
  template: SiteTemplate;
  color_mode: "LIGHT" | "DARK" | "AUTO";
  color_primary: string;
  color_secondary: string | null;
  color_accent: string | null;
  tagline: string | null;
  social: Record<string, string>;
  crest_url: string | null;
  crest_alt: string | null;
  hero_url: string | null;
  hero_alt: string | null;
  /** A CSS `object-position`, or null when the picture is centred. Every frame
   *  crops around it, so one photograph survives a wide desktop band and a
   *  nearly square one on a phone. */
  hero_focus: string | null;
  /** Whether this club can take a card. Decided server-side from whether a
   *  gateway is configured and switched on. */
  accepts_cards: boolean;
  announcement: string | null;
  tickets_url: string | null;
  tickets_label: string | null;
  palette: Record<string, string>;
  /** The footer, as the club filled it in. Every field optional. */
  contact_email: string | null;
  contact_phone: string | null;
  address: string | null;
  legal_line: string | null;
  sponsors_title: string | null;
  sponsors: Sponsor[];
}

export interface Site {
  club_id: string;
  slug: string;
  name: string;
  short_name: string;
  founded_year: number | null;
  country_code: string;
  locale: string;
  /** Every language this club publishes in. */
  locales: string[];
  timezone: string;
  /** What the club plays, and the two facts the site needs about it. */
  sport: string;
  /** "GOAL" | "POINT" | "SET" — what one unit of score is called. */
  scoring_unit: string;
  draws_possible: boolean;
  branding: Branding;
}

export interface Sponsor {
  name: string;
  url: string | null;
  logo_url: string | null;
}

export interface Team {
  id: string;
  name: string;
  code: string;
  age_group: string | null;
  level: string;
  is_academy: boolean;
}

export type Block =
  | { type: "paragraph"; text: string }
  | { type: "heading"; level: 2 | 3; text: string }
  | { type: "quote"; text: string; attribution?: string | null }
  | { type: "list"; ordered: boolean; items: string[] };

export interface ArticleSummary {
  id: string;
  slug: string;
  locale: string;
  title: string;
  excerpt: string | null;
  published_at: string | null;
  is_pinned: boolean;
  cover_url: string | null;
  /** A CSS `object-position`, or null when the picture is centred. */
  cover_focus: string | null;
  article_type: string;
}

export interface Article extends ArticleSummary {
  body: Block[];
  seo_title: string | null;
  seo_description: string | null;
  served_locale_fallback: boolean;
}

export interface SquadPlayer {
  id: string;
  name: string;
  shirt_number: number | null;
  position: string | null;
  photo_url: string | null;
}

async function currentHost(): Promise<string> {
  const incoming = await headers();
  return (
    incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "localhost"
  );
}

async function fetchPublic<T>(path: string, revalidate: number): Promise<T | null> {
  const host = await currentHost();
  const response = await fetch(`${API}/api/v1/public${path}`, {
    // The API resolves the club from this header, exactly as it would from a
    // direct browser request.
    headers: { "X-Forwarded-Host": host },
    next: { revalidate, tags: [`site:${host}`] },
  });

  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`public API ${path} failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

/** Deduplicated per request: layout and page both need the site. */
export const getSite = cache(async (): Promise<Site | null> =>
  fetchPublic<Site>("/site", 60),
);

export const getTeams = cache(async (): Promise<Team[]> =>
  (await fetchPublic<Team[]>("/teams", 120)) ?? [],
);

export interface TeamStaffMember {
  id: string;
  name: string;
  role: string;
  title: string | null;
  photo_url: string | null;
}

export const getTeamStaff = cache(
  async (teamId: string): Promise<TeamStaffMember[]> =>
    (await fetchPublic<TeamStaffMember[]>(`/teams/${teamId}/staff`, 120)) ?? [],
);

export const getSquad = cache(
  async (teamId: string): Promise<SquadPlayer[]> =>
    (await fetchPublic<SquadPlayer[]>(`/teams/${teamId}/squad`, 120)) ?? [],
);

export const getNews = cache(
  async (limit = 12): Promise<ArticleSummary[]> =>
    (await fetchPublic<ArticleSummary[]>(`/news?limit=${limit}`, 120)) ?? [],
);

export const getArticle = cache(
  async (slug: string): Promise<Article | null> =>
    fetchPublic<Article>(`/news/${encodeURIComponent(slug)}`, 120),
);

/** Dates render in the club's locale and time zone, never the server's. */
export function formatDate(iso: string | null, site: Site): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat(site.locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: site.timezone,
  }).format(new Date(iso));
}

/**
 * Brand tokens as inline custom properties.
 *
 * The palette is computed server-side — including the contrast-corrected text
 * variants — so the admin shell and the public site are themed from identical
 * maths, and a club never sees two different versions of its own blue.
 */
export function paletteToStyle(branding: Branding): Record<string, string> {
  return Object.fromEntries(
    Object.entries(branding.palette).filter(([key]) => key.startsWith("--")),
  );
}

// --- Fixtures and table ------------------------------------------------------

export interface PublicClubRef {
  name: string;
  short_name: string;
  crest_url: string | null;
}

export interface MatchEvent {
  minute: number | null;
  extra_minute: number | null;
  kind: "GOAL" | "CARD" | "SUBSTITUTION" | "VAR";
  detail: string | null;
  player_name: string | null;
  related_name: string | null;
  is_home: boolean;
}

export interface PublicMatch {
  id: string;
  competition: string;
  round_label: string | null;
  round_number: number | null;
  home: PublicClubRef;
  away: PublicClubRef;
  kickoff_at: string | null;
  /** False when only the date is known — the page then says so. */
  kickoff_is_confirmed: boolean;
  minute: number | null;
  events: MatchEvent[];
  venue_name: string | null;
  status: string;
  home_score: number | null;
  away_score: number | null;
  ticket_url: string | null;
  is_home: boolean;
}

export interface PublicTableRow {
  position: number;
  club: PublicClubRef;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goal_difference: number;
  points: number;
  form: string[];
  /** Marked by the API, so a template highlights the club without matching names. */
  is_us: boolean;
}

export async function getMatches(upcoming = true, limit = 4): Promise<PublicMatch[]> {
  // Short cache: a kick-off time can move on the morning of the match, and the
  // person checking is the one it matters to.
  return (
    (await fetchPublic<PublicMatch[]>(`/matches?upcoming=${upcoming}&limit=${limit}`, 60)) ??
    []
  );
}

export async function getTable(): Promise<PublicTableRow[]> {
  return (await fetchPublic<PublicTableRow[]>("/table", 300)) ?? [];
}

/* --- shop ------------------------------------------------------------------ */

export interface ShopVariant {
  id: string;
  label: string;
  stock: number;
}

export interface ShopProduct {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  price_minor: number;
  currency: string;
  cover_url: string | null;
  variants: ShopVariant[];
}

export interface BasketLine {
  variant_id: string;
  product_name: string;
  variant_label: string;
  unit_price_minor: number;
  quantity: number;
  total_minor: number;
  cover_url: string | null;
}

export interface Basket {
  token: string;
  currency: string;
  lines: BasketLine[];
  total_minor: number;
}

/** Short revalidate: a stock count that lies is worse than a slower page. */
export async function getShop(): Promise<ShopProduct[]> {
  return (await fetchPublic<ShopProduct[]>("/shop", 30)) ?? [];
}


/* --- the club's record ------------------------------------------------------ */

export interface SeasonRecord {
  season: string;
  competition: string;
  position: number | null;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  points: number;
  outcome: string | null;
}

export interface ClubHistory {
  founded_year: number | null;
  venue_name: string | null;
  venue_capacity: number | null;
  city: string | null;
  seasons: SeasonRecord[];
  honours: string[];
}

export async function getHistory(): Promise<ClubHistory | null> {
  return fetchPublic<ClubHistory>("/history", 3600);
}

/* --- tickets ---------------------------------------------------------------- */

export interface TicketedEventSummary {
  slug: string;
  name: string;
  opponent_name: string | null;
  competition_label: string | null;
  kickoff_at: string;
  doors_open_at: string | null;
  currency: string;
  available: number;
}

export interface TicketSectionAvailability {
  section_id: string;
  code: string;
  name: string;
  stand: string;
  kind: "RESERVED" | "GENERAL_ADMISSION";
  price_zone_code: string | null;
  total: number;
  available: number;
}

export interface TicketZone {
  id: string;
  name: string;
  code: string;
  colour: string;
}

export interface TicketLayoutSection {
  id: string;
  name: string;
  code: string;
  kind: "RESERVED" | "GENERAL_ADMISSION";
  capacity: number;
  geometry: { points?: [number, number][] };
  price_zone: TicketZone | null;
}

export interface TicketLayoutStand {
  id: string;
  name: string;
  code: string;
  geometry: { points?: [number, number][] };
  sections: TicketLayoutSection[];
}

export interface TicketEventDetail {
  slug: string;
  name: string;
  kickoff_at: string;
  doors_open_at: string | null;
  currency: string;
  max_per_customer: number;
  hold_minutes: number;
  layout: {
    venue: { name: string; city: string | null };
    price_zones: TicketZone[];
    stands: TicketLayoutStand[];
    gates: { code: string; name: string; section_ids: string[] }[];
  };
  availability: TicketSectionAvailability[];
  prices: Record<string, { amount_minor: number; currency: string }>;
}

/**
 * Matches on sale. Cached briefly, like the shop: a page that says a match is
 * available after it sold out is worse than one that loads a moment slower.
 */
export async function getTicketedEvents(): Promise<TicketedEventSummary[]> {
  return (await fetchPublic<TicketedEventSummary[]>("/tickets/events", 30)) ?? [];
}

/**
 * One match, with its frozen layout and a free/total count per sector.
 *
 * Never cached. Availability is the whole point of the page, and a supporter
 * choosing from a thirty-second-old map is a supporter told a seat is free and
 * then refused it at checkout.
 */
export async function getTicketedEvent(slug: string): Promise<TicketEventDetail | null> {
  return fetchPublic<TicketEventDetail>(`/tickets/events/${slug}`, 0);
}
