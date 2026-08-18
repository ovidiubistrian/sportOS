/**
 * API contract types.
 *
 * Hand-written for the vertical slice. Phase 0 replaces this file with output
 * generated from `docs/api/openapi.v1.json` in CI, so drift between the server
 * and the client becomes a failing build rather than a runtime surprise.
 */

export interface PageMeta {
  limit: number;
  offset: number | null;
  total: number | null;
  total_is_estimate: boolean;
  next_cursor: string | null;
  has_more: boolean;
}

export interface Page<T> {
  data: T[];
  page: PageMeta;
}

export interface TenantSummary {
  id: string;
  slug: string;
  legal_name: string;
  trading_name: string | null;
  default_locale: string;
  /** Every language this tenant publishes in. */
  supported_locales: string[];
  default_currency: string;
  /** Which country's divisions to ask the results provider for. */
  country_code: string;
  timezone: string;
  status: "PENDING" | "ACTIVE" | "SUSPENDED" | "CLOSED";
  is_demo: boolean;
}

export interface ClubSummary {
  id: string;
  slug: string;
  display_name: string;
  short_name: string;
  template: SiteTemplate;
  color_primary: string;
  /** Derived server-side, including contrast-corrected text variants. */
  palette: Record<string, string>;
  /** The club's row in the shared competition directory, once it has one. */
  directory_club_id: string | null;
}

export type SiteTemplate = "CLASSIC" | "BOLD" | "COMPACT" | "EDITORIAL";
export type ColorMode = "LIGHT" | "DARK" | "AUTO";

/** Per-colour readability assessment, shown next to each picker. */
export interface ColorCheck {
  color: string;
  /** Black or white — whichever is readable on a fill of this colour. */
  on_color: string;
  /** The colour adjusted until it is readable as text on white. */
  text_variant: string;
  was_adjusted: boolean;
  contrast_on_white: number;
  meets_aa_as_text: boolean;
  meets_aa_as_surface: boolean;
  advice: string | null;
}

export interface Branding {
  club_id: string;
  template: SiteTemplate;
  color_mode: ColorMode;
  color_primary: string;
  color_secondary: string | null;
  color_accent: string | null;
  tagline: string | null;
  social: Record<string, string>;
  /** Resolved from the asset id server-side; null once the image is deleted. */
  crest_url: string | null;
  hero_url: string | null;
  crest_media_id: string | null;
  hero_media_id: string | null;
  /** On the club, not the branding — edited here because this is the page
   *  where a club decides how its name appears. */
  display_name: string | null;
  short_name: string | null;
  palette: Record<string, string>;
  checks: Record<string, ColorCheck>;
  available_templates: SiteTemplate[];
  available_color_modes: ColorMode[];
  /** The footer. Every field optional; a club that fills none gets its name. */
  contact_email: string | null;
  contact_phone: string | null;
  address: string | null;
  legal_line: string | null;
  sponsors_title: string | null;
  sponsors: { name: string; url: string | null; media_id: string | null; logo_url?: string | null }[];
}

export interface BrandingUpdate {
  template?: SiteTemplate;
  color_mode?: ColorMode;
  color_primary?: string;
  color_secondary?: string | null;
  color_accent?: string | null;
  tagline?: string | null;
  social?: Record<string, string>;
  crest_media_id?: string | null;
  hero_media_id?: string | null;
  display_name?: string;
  short_name?: string;
  contact_email?: string | null;
  contact_phone?: string | null;
  address?: string | null;
  legal_line?: string | null;
  sponsors_title?: string | null;
  sponsors?: { name: string; url?: string | null; media_id?: string | null }[];
}

/**
 * One club the user may enter, and the tenant it belongs to.
 *
 * The admin is one application at one address; the club slug in the URL says
 * which club you are working in. This list is what makes that resolvable at
 * sign-in, before any tenant has been chosen — and it is a routing aid, never
 * an authorization input.
 */
export interface Workspace {
  tenant_id: string;
  tenant_name: string;
  club: ClubSummary;
}

export interface MeResponse {
  user_id: string;
  email: string;
  is_platform_user: boolean;
  active_tenant: TenantSummary | null;
  tenants: TenantSummary[];
  clubs: ClubSummary[];
  /** Every club across every tenant this user belongs to. */
  workspaces: Workspace[];
  permissions: string[];
}

export interface TeamSummary {
  id: string;
  name: string;
  code: string;
  age_group: string | null;
}

export interface Team extends TeamSummary {
  club_id: string;
  gender: string;
  level: string;
  is_academy: boolean;
  status: string;
  /** What this team plays. Inherited from the club unless it is the exception. */
  sport: string;
}

/** A sport the platform knows how to run, and what differs about it. */
export interface Sport {
  key: string;
  name: string;
  scoring_unit: string;
  draws_possible: boolean;
  period_count: number;
  period_minutes: number | null;
  tracks_minute: boolean;
  positions: string[];
  event_kinds: string[];
  /** Whether a league feed can fill fixtures in, or the club enters them. */
  has_provider: boolean;
}

export type PlayerStatus =
  | "TRIAL"
  | "REGISTERED"
  | "LOANED_OUT"
  | "INACTIVE"
  | "DEPARTED";

export interface PlayerSummary {
  id: string;
  person_id: string;
  display_name: string;
  status: PlayerStatus;
  primary_position: string | null;
  shirt_number: number | null;
  team: TeamSummary | null;
  birth_date: string | null;
  photo_url: string | null;
}

export interface PlayerDetail extends PlayerSummary {
  photo_media_id: string | null;
  first_name: string;
  last_name: string;
  secondary_positions: string[];
  preferred_foot: string | null;
  nationality: string[];
  federation_id: string | null;
  joined_club_on: string | null;
  left_club_on: string | null;
  club_id: string;
  created_at: string;
  updated_at: string;
}

export interface PlayerFilters {
  club_id?: string;
  team_id?: string;
  status?: string;
  q?: string;
  limit?: number;
  offset?: number;
  with_total?: boolean;
}

/** Stable error codes. Branch on these, never on `message`. */
export type ApiErrorCode =
  | "VALIDATION_ERROR"
  | "NOT_FOUND"
  | "CONFLICT"
  | "UNAUTHENTICATED"
  | "STEP_UP_REQUIRED"
  | "PERMISSION_DENIED"
  | "TENANT_MISMATCH"
  | "TENANT_CONTEXT_MISSING"
  | "TENANT_SUSPENDED"
  | "FEATURE_NOT_ENABLED"
  | "LIMIT_EXCEEDED"
  | "RATE_LIMITED"
  | "INTERNAL_ERROR";

export interface ApiErrorBody {
  code: ApiErrorCode | string;
  message: string;
  details: Record<string, unknown>;
  request_id: string | null;
}

// --- Newsroom --------------------------------------------------------------

export type ContentStatus =
  | "DRAFT"
  | "IN_REVIEW"
  | "SCHEDULED"
  | "PUBLISHED"
  | "ARCHIVED";

export type ArticleType =
  | "ANNOUNCEMENT"
  | "MATCH_REPORT"
  | "MATCH_PREVIEW"
  | "SIGNING"
  | "DEPARTURE"
  | "ACADEMY"
  | "INTERVIEW";

/**
 * A body block. Deliberately not HTML — the four public templates each render
 * these in their own character, and text cannot become markup.
 */
export type Block =
  | { type: "paragraph"; text: string }
  | { type: "heading"; level: 2 | 3; text: string }
  | { type: "quote"; text: string; attribution?: string | null }
  | { type: "list"; ordered: boolean; items: string[] };

export interface TranslationSummary {
  locale: string;
  title: string;
  slug: string;
  status: "DRAFT" | "READY";
  /** Publishable, not merely present: a title with an empty body is a stub. */
  is_complete: boolean;
}

export interface TranslationDetail {
  locale: string;
  title: string;
  slug: string;
  excerpt: string | null;
  body: Block[];
  seo_title: string | null;
  seo_description: string | null;
  status: "DRAFT" | "READY";
}

export interface ContentSummary {
  id: string;
  club_id: string;
  kind: string;
  article_type: ArticleType;
  status: ContentStatus;
  published_at: string | null;
  scheduled_for: string | null;
  is_pinned: boolean;
  cover_media_id: string | null;
  cover_url: string | null;
  title: string;
  locales: TranslationSummary[];
  updated_at: string;
}

export interface ContentDetail extends ContentSummary {
  translations: TranslationDetail[];
  category_id: string | null;
}

export interface ContentFilters {
  club_id?: string;
  status?: ContentStatus;
  article_type?: ArticleType;
  q?: string;
  limit?: number;
  offset?: number;
  with_total?: boolean;
}

export interface ContentCreate {
  club_id: string;
  article_type: ArticleType;
  /** Optional at creation: the image is uploaded to the club's library, which
   *  does not need the article to exist yet. */
  cover_media_id?: string | null;
  translation: {
    locale: string;
    title: string;
    body?: Block[];
    excerpt?: string | null;
    slug?: string | null;
  };
}

export interface TranslationInput {
  locale: string;
  title: string;
  slug?: string | null;
  excerpt?: string | null;
  body: Block[];
  seo_title?: string | null;
  seo_description?: string | null;
  status?: "DRAFT" | "READY" | null;
}

// --- Writing assistant -----------------------------------------------------

export interface ArticleTypeSpec {
  key: ArticleType;
  name: string;
  description: string;
  skeleton: Block[];
}

export interface AssistantStatus {
  available: boolean;
  /** Present whenever `available` is false. Shown verbatim to the editor. */
  reason: string | null;
  requests_used: number;
  requests_limit: number | null;
  article_types: ArticleTypeSpec[];
}

export interface AssistRequest {
  content_item_id?: string | null;
  locale: string;
  title: string;
  blocks: Block[];
}

export interface PolishSuggestion {
  usage_id: string;
  blocks: Block[];
  summary_of_changes: string;
  requests_used: number;
  duration_ms: number;
}

export interface HeadlineSuggestion {
  usage_id: string;
  headlines: string[];
  requests_used: number;
  duration_ms: number;
}


// --- Media -----------------------------------------------------------------

/** What an image is *for*. Decides where it may be rendered and how it crops. */
export type MediaPurpose =
  | "CREST"
  | "HERO"
  | "PARTNER_LOGO"
  | "COMPETITION_BADGE"
  | "ARTICLE_IMAGE"
  | "TEAM_PHOTO"
  | "PLAYER_PHOTO";

export interface MediaAsset {
  id: string;
  club_id: string;
  purpose: MediaPurpose;
  /** Stable and unsigned — public site media is served straight from storage. */
  url: string;
  width: number;
  height: number;
  size_bytes: number;
  content_type: string;
  alt_text: string | null;
  /** A label so an editor recognises their own upload. Never part of the URL. */
  original_filename: string | null;
  /** Where the picture actually is, as a fraction of its own width and height.
   *  0.5/0.5 is the centre, which is what every frame cropped to before this
   *  existed. */
  focal_x: number;
  focal_y: number;
}


// --- Sign-up ---------------------------------------------------------------

export interface PlatformLocale {
  code: string;
  /** In the language itself — a speaker scans for their own word. */
  endonym: string;
  english_name: string;
}

export interface SlugCheck {
  slug: string;
  available: boolean;
  /** Offered when the obvious address is taken. */
  suggestion: string | null;
}

export interface SignUpInput {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  club_name: string;
  slug: string;
  country_code: string;
  locale: string;
}

export interface SignUpResult {
  club_slug: string;
  email: string;
  verification_required: boolean;
}

export interface TeamInput {
  club_id: string;
  name: string;
  code: string;
  gender?: string;
  age_group?: string | null;
  level?: string;
  is_academy?: boolean;
  sport?: string | null;
}

export interface TeamUpdate {
  name?: string;
  code?: string;
  gender?: string;
  age_group?: string | null;
  level?: string;
  is_academy?: boolean;
  status?: "ACTIVE" | "ARCHIVED";
  sport?: string;
}

export interface PlayerUpdate {
  first_name?: string;
  last_name?: string;
  birth_date?: string | null;
  nationality?: string[];
  status?: string;
  primary_position?: string | null;
  secondary_positions?: string[];
  preferred_foot?: string | null;
  federation_id?: string | null;
  photo_media_id?: string | null;
  joined_club_on?: string | null;
  left_club_on?: string | null;
}

export interface RegistrationChange {
  team_id: string | null;
  season_id?: string | null;
  shirt_number?: number | null;
}

/* --- competitions ---------------------------------------------------------- */

export interface Competition {
  id: string;
  key: string;
  name: string;
  short_name: string | null;
  format: "LEAGUE" | "KNOCKOUT" | "GROUP_KNOCKOUT";
  scope: string;
  tier: number | null;
}

/** A season the club has actually entered — what a fixture is filed under. */
export interface CompetitionEntry {
  id: string;
  competition_id: string;
  competition_name: string;
  competition_format: Competition["format"];
  season_name: string;
  is_current: boolean;
}

export interface DirectoryClub {
  id: string;
  name: string;
  short_name: string;
  crest_url: string | null;
}

export type MatchStatus =
  | "SCHEDULED"
  // A match that has kicked off and not finished. The backend has always had
  // it; this type did not, so a live fixture could not be represented here.
  | "LIVE"
  | "POSTPONED"
  | "CANCELLED"
  | "FINISHED"
  | "AWARDED";

export interface Match {
  id: string;
  competition_season_id: string;
  competition_name: string;
  home: DirectoryClub;
  away: DirectoryClub;
  round_kind: string;
  round_number: number | null;
  round_label: string | null;
  /** Set when the club has corrected the feed's label. */
  round_label_override?: string | null;
  /** Minute of play while the match is on; null otherwise. */
  minute?: number | null;
  kickoff_at: string | null;
  kickoff_is_confirmed: boolean;
  venue_name: string | null;
  status: MatchStatus;
  home_score: number | null;
  away_score: number | null;
  ticket_url: string | null;
  is_home: boolean;
}

export interface TableRow {
  position: number;
  club: DirectoryClub;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
  form: string[];
}

export interface JoinCompetitionInput {
  club_id: string;
  competition_id: string;
  season_name: string;
  start_date: string;
  end_date: string;
}

/**
 * What entering a competition did — including to the results feed.
 *
 * The feed is reported rather than silent because "connected" and "this
 * division is not covered" ask completely different things of the club next,
 * and it should not have to go looking to find out which happened.
 */
export interface JoinedCompetition {
  competition: Competition;
  feed_connected: boolean;
  feed_message: string;
}

/** One division the provider covers, as a club would recognise it. */
export interface ProviderLeague {
  id: string;
  name: string;
  country: string | null;
  logo: string | null;
  tier: number | null;
  /** The season the provider currently holds — what to ask for next. */
  season: number | null;
}

/**
 * `available: false` covers the two cases a club must tell apart without
 * reading an error: no provider key on the platform, and no coverage for the
 * country. Both mean the same next step, and neither is a fault.
 */
export interface ProviderCatalogue {
  available: boolean;
  reason: string | null;
  leagues: ProviderLeague[];
}

/** How a club's results feed is set up, and whether it has ever run. */
export interface FeedSettings {
  club_id: string;
  mode: "FEED" | "MANUAL";
  provider_team_id: string | null;
  provider_team_name: string | null;
  season_year: number | null;
  sync_fixtures: boolean;
  sync_standings: boolean;
  sync_live: boolean;
  live_interval_minutes: number;
  fixtures_interval_hours: number;
  last_fixtures_at: string | null;
  last_live_at: string | null;
  last_error: string | null;
  /** False where the platform has no provider key at all. */
  provider_available: boolean;
}

export interface FeedUpdate {
  mode?: "FEED" | "MANUAL";
  provider_team_id?: string | null;
  provider_team_name?: string | null;
  season_year?: number | null;
}

export interface ProviderTeam {
  id: string;
  name: string;
  country: string | null;
  logo: string | null;
  founded: number | null;
}

export interface MatchCreate {
  club_id: string;
  competition_season_id: string;
  opponent_club_id: string;
  at_home: boolean;
  round_kind?: string;
  round_number?: number | null;
  round_label?: string | null;
  kickoff_at?: string | null;
  kickoff_is_confirmed?: boolean;
  venue_name?: string | null;
  ticket_url?: string | null;
}

export interface MatchUpdate {
  kickoff_at?: string | null;
  kickoff_is_confirmed?: boolean;
  venue_name?: string | null;
  ticket_url?: string | null;
  status?: MatchStatus;
  home_score?: number | null;
  away_score?: number | null;
  /**
   * The club's correction when the feed mislabels a round. Stored separately
   * from the provider's own label, so a sync does not undo it — and the one
   * field a feed fixture will accept.
   */
  round_label_override?: string | null;
}

/* --- shop ------------------------------------------------------------------ */

export interface ProductVariant {
  id: string;
  label: string;
  sku: string | null;
  stock: number;
  sort_order: number;
}

export interface Product {
  id: string;
  club_id: string;
  slug: string;
  name: string;
  description: string | null;
  /** Minor units. Never a float — see backend/app/core/money.py. */
  price_minor: number;
  currency: string;
  cover_media_id: string | null;
  cover_url: string | null;
  is_active: boolean;
  sort_order: number;
  variants: ProductVariant[];
}

export interface VariantInput {
  id?: string;
  label: string;
  sku?: string | null;
  stock: number;
  sort_order?: number;
}

export interface ProductInput {
  club_id: string;
  name: string;
  description?: string | null;
  price_minor: number;
  cover_media_id?: string | null;
  is_active?: boolean;
  sort_order?: number;
  variants?: VariantInput[];
}

export interface ProductChanges {
  name?: string;
  description?: string | null;
  price_minor?: number;
  cover_media_id?: string | null;
  is_active?: boolean;
  sort_order?: number;
  variants?: VariantInput[];
}

export type OrderStatus =
  | "PENDING"
  | "AWAITING_COLLECTION"
  | "COLLECTED"
  | "CANCELLED";

export interface ShopOrderLine {
  description: string;
  unit_price_minor: number;
  quantity: number;
  total_minor: number;
}

export interface ShopOrder {
  id: string;
  reference: string;
  status: OrderStatus;
  currency: string;
  total_minor: number;
  buyer_name: string;
  buyer_email: string | null;
  buyer_phone: string | null;
  note: string | null;
  placed_at: string | null;
  collected_at: string | null;
  lines: ShopOrderLine[];
}

/* --- the super-admin console ----------------------------------------------- */

export interface PlatformTenant {
  id: string;
  slug: string;
  name: string;
  status: "PENDING" | "ACTIVE" | "SUSPENDED" | "CLOSED";
  country_code: string;
  default_locale: string;
  supported_locales: string[];
  default_currency: string;
  plan: string | null;
  subscription_status: string | null;
  trial_ends_at: string | null;
  clubs: number;
  players: number;
  created_at: string;
}

export interface PlatformPlan {
  id: string;
  key: string;
  name: string;
  tier: string;
  version: number;
  features: { feature_key: string; enabled: boolean; limit_value: number | null }[];
}

export interface PlatformCompetition {
  id: string;
  country_code: string | null;
  key: string;
  name: string;
  short_name: string | null;
  format: "LEAGUE" | "KNOCKOUT" | "GROUP_KNOCKOUT";
  scope: string;
  tier: number | null;
  sort_order: number;
  is_active: boolean;
  /** How many club-seasons are filed against it. */
  seasons: number;
}


/** Somebody who works at the club, and the one job they hold. */
export interface StaffMember {
  user_id: string;
  email: string;
  display_name: string;
  role_key: string;
  role_name: string;
  club_id: string | null;
  team_id: string | null;
  scope_label: string | null;
  /** Invited, never signed in. */
  pending: boolean;
  last_login_at: string | null;
  granted_at: string | null;
}

export interface StaffRole {
  key: string;
  name: string;
  scope_level: "TENANT" | "CLUB" | "TEAM";
  description: string;
  /** False when the caller holds less than the role would grant. */
  grantable: boolean;
}

export interface StaffInvite {
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  club_id?: string | null;
  team_id?: string | null;
  /**
   * Optional. Left empty, the person receives an invitation link and picks
   * their own password. Supplied, it is a starting password they are forced
   * to change the first time they sign in.
   */
  temporary_password?: string | null;
}

/** Somebody on a team's touchline, as the club presents them. */
export interface TeamStaffMember {
  id: string;
  team_id: string;
  person_id: string;
  name: string;
  role: string;
  title: string | null;
  photo_media_id: string | null;
  is_public: boolean;
  sort_order: number;
}

export interface TeamStaffInput {
  person_id?: string | null;
  first_name?: string;
  last_name?: string;
  role: string;
  title?: string | null;
  photo_media_id?: string | null;
  is_public?: boolean;
  sort_order?: number;
}

export const TEAM_STAFF_ROLES = [
  "HEAD_COACH",
  "ASSISTANT_COACH",
  "GOALKEEPING_COACH",
  "FITNESS_COACH",
  "ANALYST",
  "PHYSIO",
  "DOCTOR",
  "TEAM_MANAGER",
  "KIT_MANAGER",
  "PRESS_OFFICER",
  "PRESIDENT",
  "DIRECTOR",
] as const;

/* --- analytics ------------------------------------------------------------- */

export interface AnalyticsMetric {
  value: number;
  previous: number;
  /** Null when there is nothing to compare against — not the same as no change. */
  change_percent: number | null;
}

export interface AnalyticsPoint {
  day: string;
  sessions: number;
  views: number;
}

export interface AnalyticsCount {
  label: string;
  value: number;
  unique: number | null;
}

export interface AnalyticsFunnelStep {
  label: string;
  value: number;
  of_total_percent: number;
  from_previous_percent: number | null;
}

export interface AnalyticsOverview {
  range: string;
  since: string;
  until: string;
  live: number;
  sessions: AnalyticsMetric;
  visitors: AnalyticsMetric;
  views: AnalyticsMetric;
  signups: AnalyticsMetric;
  conversion_percent: number;
  conversion_previous_percent: number;
  series: AnalyticsPoint[];
  funnel: AnalyticsFunnelStep[];
  sources: AnalyticsCount[];
  pages: AnalyticsCount[];
  devices: AnalyticsCount[];
  browsers: AnalyticsCount[];
  campaigns: AnalyticsCount[];
  /** Empty when no geography database is installed. */
  countries: AnalyticsCount[];
  cities: AnalyticsCount[];
}

export type AnalyticsRange = "today" | "7d" | "30d" | "90d";

/* --- email marketing ------------------------------------------------------- */

export interface EmailTemplate {
  id: string;
  club_id: string;
  key: string;
  name: string;
  subject: string;
  preheader: string | null;
  blocks: Block[];
  cta_label: string | null;
  cta_url: string | null;
  locale: string | null;
  is_active: boolean;
}

export interface EmailTemplateInput {
  club_id: string;
  key: string;
  name: string;
  subject: string;
  preheader?: string | null;
  blocks?: Block[];
  cta_label?: string | null;
  cta_url?: string | null;
}

export interface EmailTemplateChanges {
  name?: string;
  subject?: string;
  preheader?: string | null;
  blocks?: Block[];
  cta_label?: string | null;
  cta_url?: string | null;
  is_active?: boolean;
}

export interface EmailPreview {
  subject: string;
  html: string;
  text: string;
}

/** Who a campaign is aimed at. Both pools carry their own consent record. */
export type CampaignAudience = "NEWSLETTER" | "SUPPORTERS" | "EVERYONE";

export type CampaignKind = "NEWS" | "OFFER" | "MATCHDAY" | "MEMBERSHIP" | "ANNOUNCEMENT";

export interface Campaign {
  id: string;
  club_id: string;
  template_id: string;
  name: string;
  kind: CampaignKind;
  audience: CampaignAudience;
  locale: string | null;
  status: "DRAFT" | "SCHEDULED" | "SENDING" | "SENT" | "FAILED" | "CANCELLED";
  total: number;
  sent: number;
  failed: number;
  opened: number;
  unsubscribed: number;
  error: string | null;
}

export interface CampaignInput {
  club_id: string;
  template_id: string;
  name: string;
  kind?: CampaignKind;
  audience?: CampaignAudience;
  locale?: string | null;
}

export interface AudienceSize {
  total: number;
  newsletter: number;
  supporters: number;
  /** Which way the club's email currently leaves — SMTP or MAILGUN. */
  provider: string;
}

// --- Card payments ----------------------------------------------------------

/** A tenant's gateway, as the settings screen sees it. Never the password. */
export interface PaymentGateway {
  provider: string;
  is_live: boolean;
  sandbox: boolean;
  user_name: string;
  has_password: boolean;
  child_id: string | null;
  updated_at: string | null;
}

export interface PaymentGatewayInput {
  user_name: string;
  /** Omitted on an edit: it cannot be read back, so it cannot be retyped. */
  password?: string;
  sandbox: boolean;
  child_id?: string | null;
  is_live: boolean;
}

export interface PaymentGatewayCheck {
  ok: boolean;
  error?: string | null;
  sandbox?: boolean;
}

/** One call to a gateway. The detail carries what was sent and returned. */
export interface PaymentCall {
  id: string;
  provider: string;
  endpoint: string;
  order_ref: string | null;
  provider_order_id: string | null;
  ok: boolean;
  http_status: number | null;
  error_code: string | null;
  error_message: string | null;
  latency_ms: number | null;
  created_at: string;
}

export interface PaymentCallDetail extends PaymentCall {
  sent: Record<string, unknown>;
  received: Record<string, unknown>;
}

// --- stadium & ticketing ---------------------------------------------------

export interface Venue {
  id: string;
  club_id: string;
  name: string;
  code: string;
  address: string | null;
  city: string | null;
  country_code: string;
  timezone: string;
  currency: string;
  expected_capacity: number;
  pitch_orientation: string;
  cover_media_id: string | null;
}

/** One versioned layout. Immutable once `status` is PUBLISHED. */
export interface VenueConfiguration {
  id: string;
  venue_id: string;
  name: string;
  version: number;
  status: "DRAFT" | "PUBLISHED" | "ARCHIVED";
  valid_from: string | null;
  total_capacity: number;
  published_at: string | null;
  forked_from_id: string | null;
}

export interface PriceZone {
  id: string;
  name: string;
  code: string;
  colour: string;
}

/**
 * The serialised layout — the same shape whether it comes from a live
 * configuration or from a match's frozen snapshot, so one map component draws
 * both.
 */
export interface StadiumLayout {
  venue: { id: string | null; name: string; city: string | null; pitch_orientation: string };
  configuration: { id: string; name: string; version: number };
  price_zones: PriceZone[];
  access_zones: { id: string; name: string; code: string }[];
  stands: LayoutStand[];
  gates: LayoutGate[];
}

export interface LayoutStand {
  id: string;
  name: string;
  code: string;
  geometry: { points?: [number, number][] };
  sections: LayoutSection[];
}

export interface LayoutSection {
  id: string;
  name: string;
  code: string;
  kind: "RESERVED" | "GENERAL_ADMISSION";
  capacity: number;
  geometry: { points?: [number, number][] };
  price_zone: PriceZone | null;
  rows: { id: string; label: string; seats: LayoutSeat[] }[];
}

export interface LayoutSeat {
  id: string;
  label: string;
  kind: "STANDARD" | "WHEELCHAIR" | "COMPANION" | "OBSTRUCTED_VIEW";
  blocked: boolean;
  index: number;
  zone: string | null;
}

export interface LayoutGate {
  id: string;
  name: string;
  code: string;
  kind: string;
  supporter_side: string;
  is_accessible: boolean;
  access_zone: { id: string; name: string; code: string } | null;
  section_ids: string[];
}

/** A finding from the review step. ERROR blocks publication; WARNING does not. */
export interface ConfigurationFinding {
  code: string;
  message: string;
  severity: "ERROR" | "WARNING";
  subject: string | null;
}

export interface ConfigurationReview {
  total_capacity: number;
  reserved_seats: number;
  general_admission: number;
  blocked_seats: number;
  accessible_seats: number;
  by_stand: { id: string; name: string; capacity: number }[];
  by_section: {
    id: string;
    stand: string;
    name: string;
    code: string;
    kind: string;
    capacity: number;
  }[];
  publishable: boolean;
  findings: ConfigurationFinding[];
}

export interface TicketedEvent {
  id: string;
  name: string;
  slug: string;
  status: "DRAFT" | "PUBLISHED" | "CLOSED" | "CANCELLED";
  category: "A" | "B" | "C";
  kickoff_at: string;
  doors_open_at: string | null;
  sales_start_at: string | null;
  sales_end_at: string | null;
  is_public: boolean;
  currency: string;
  venue_id: string;
  opponent_name: string | null;
  competition_label: string | null;
  max_per_customer: number;
  avoid_orphan_seats: boolean;
}

export interface EventCapacity {
  total: number;
  sellable: number;
  sold: number;
  available: number;
  held: number;
  reserved: number;
  blocked: number;
  allocated: number;
  complimentary: number;
  /** Against sellable capacity, not architectural — a closed stand is not empty seats. */
  occupancy: number;
  by_state: Record<string, number>;
  by_stand: { stand: string; total: number; sold: number }[];
}

export interface SectionAvailability {
  section_id: string;
  code: string;
  name: string;
  stand: string;
  kind: "RESERVED" | "GENERAL_ADMISSION";
  price_zone_code: string | null;
  total: number;
  available: number;
}

export interface EventLayout {
  source_version: number;
  source_name: string;
  total_capacity: number;
  payload: StadiumLayout;
  availability: SectionAvailability[];
}

export interface TicketType {
  id: string;
  name: string;
  code: string;
  requires_proof: boolean;
  is_complimentary: boolean;
  is_away: boolean;
  is_active: boolean;
}

/** One cell of the price zone x ticket type grid. `source` says where it came from. */
export interface PriceCell {
  zone_code: string;
  ticket_type_id: string;
  ticket_type_code: string;
  ticket_type_name: string;
  amount_minor: number | null;
  vat_rate_bp?: number;
  vat_included?: boolean;
  fee_minor?: number;
  source: "VENUE" | "SEASON" | "EVENT" | null;
  price_list_id?: string;
  rule_id?: string;
}

export interface PricingMatrix {
  currency: string;
  ticket_types: { id: string; code: string; name: string; is_complimentary: boolean }[];
  zone_codes: string[];
  cells: PriceCell[];
}

export interface Allocation {
  id: string;
  kind: "HARD_HOLD" | "SOFT_ALLOCATION";
  reason: string;
  name: string;
  owner_name: string | null;
  seat_count: number;
  expires_at: string | null;
  released_at: string | null;
  note: string | null;
}

export interface SeasonProduct {
  id: string;
  name: string;
  status: "DRAFT" | "ON_SALE" | "CLOSED";
  price_minor: number;
  currency: string;
  eligibility: string;
  is_transferable: boolean;
  matches: number;
  sold: number;
}

export interface IssuedTicket {
  id: string;
  ticket_number: string;
  status: "ISSUED" | "VOID" | "REFUNDED";
  ticket_type: string;
  holder_name: string | null;
  price_minor: number;
  vat_minor: number;
  fee_minor: number;
  currency: string;
  issued_at: string | null;
}

export interface EventReport {
  capacity: EventCapacity;
  scans: ScanCounts;
  tickets_issued: number;
  season_tickets: number;
  revenue: {
    gross_minor: number;
    vat_minor: number;
    fees_minor: number;
    net_minor: number;
  };
  by_ticket_type: { ticket_type: string; count: number; gross_minor: number }[];
}

/** Every verdict the scanner can return. Machine-readable by design. */
export type ScanResult =
  | "VALID"
  | "ALREADY_USED"
  | "WRONG_GATE"
  | "WRONG_EVENT"
  | "NOT_YET_VALID"
  | "EXPIRED"
  | "CANCELLED"
  | "REFUNDED"
  | "DEVICE_REVOKED"
  | "UNKNOWN_CREDENTIAL";

export interface ScanVerdict {
  result: ScanResult;
  scan_id: string | null;
  ticket_number: string | null;
  holder_name: string | null;
  ticket_type: string | null;
  seat: string | null;
  gate_code: string | null;
  scanned_at: string | null;
  /** Set on ALREADY_USED: the first entry's time and gate. */
  first_seen_at: string | null;
  first_seen_gate: string | null;
}

export interface ScanCounts {
  admitted: number;
  issued: number;
  no_shows: number;
  refused: number;
  by_result: Record<string, number>;
  by_gate: { gate_code: string | null; admitted: number }[];
  recent?: RecentScan[];
}

export interface RecentScan {
  id: string;
  result: ScanResult;
  gate_code: string | null;
  scan_type: "ENTRY" | "EXIT";
  server_at: string;
  seat: string | null;
  was_offline: boolean;
}

export interface EventGate {
  code: string;
  name: string;
  kind: string;
  is_accessible: boolean;
}

/** What a club types in when the feed is behind. */
export interface MatchEventInput {
  kind: "GOAL" | "CARD" | "SUBSTITUTION" | "VAR";
  minute?: number | null;
  extra_minute?: number | null;
  /** The provider's own vocabulary — "Yellow Card", "Normal Goal", "Penalty". */
  detail?: string | null;
  player_name?: string | null;
  related_name?: string | null;
  is_home: boolean;
}

export interface MatchEventEntry extends MatchEventInput {
  id: string;
  /** PROVIDER or CLUB. Only a club's own entries can be removed. */
  source: string;
}
