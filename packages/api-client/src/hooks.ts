import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { createContext, useContext } from "react";

import type { ApiClient } from "./client";
import { ApiError } from "./client";
import type {
  Allocation,
  AnalyticsOverview,
  AnalyticsRange,
  AssistRequest,
  AssistantStatus,
  AudienceSize,
  Branding,
  ConfigurationReview,
  BrandingUpdate,
  Campaign,
  CampaignAudience,
  CampaignInput,
  Competition,
  CompetitionEntry,
  ContentCreate,
  ContentDetail,
  ContentFilters,
  ContentStatus,
  ContentSummary,
  DirectoryClub,
  EventCapacity,
  EventGate,
  EventLayout,
  EventReport,
  EmailPreview,
  EmailTemplate,
  EmailTemplateChanges,
  EmailTemplateInput,
  FeedSettings,
  FeedUpdate,
  HeadlineSuggestion,
  JoinCompetitionInput,
  JoinedCompetition,
  Match,
  MatchCreate,
  MatchUpdate,
  MeResponse,
  MediaAsset,
  MediaPurpose,
  Page,
  PaymentCall,
  PaymentCallDetail,
  PaymentGateway,
  PaymentGatewayCheck,
  PaymentGatewayInput,
  PlatformCompetition,
  PlatformLocale,
  PlatformPlan,
  PlatformTenant,
  PlayerDetail,
  PlayerFilters,
  PlayerSummary,
  PlayerUpdate,
  PolishSuggestion,
  Product,
  ProductChanges,
  ProductInput,
  ProviderCatalogue,
  ProviderTeam,
  RegistrationChange,
  ShopOrder,
  SignUpInput,
  SignUpResult,
  SlugCheck,
  Sport,
  StaffInvite,
  StaffMember,
  StaffRole,
  TableRow,
  Team,
  TeamInput,
  TeamStaffInput,
  TeamStaffMember,
  TeamUpdate,
  TranslationInput,
  IssuedTicket,
  PricingMatrix,
  ScanCounts,
  ScanVerdict,
  SeasonProduct,
  StadiumLayout,
  TicketType,
  TicketedEvent,
  Venue,
  VenueConfiguration,
  MatchEventEntry,
  MatchEventInput,
} from "./types";

const ApiContext = createContext<ApiClient | null>(null);
export const ApiProvider = ApiContext.Provider;

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) throw new Error("useApi must be used inside an <ApiProvider>");
  return client;
}

/** Structured, hierarchical keys so mutations can invalidate precisely. */
export const queryKeys = {
  me: ["me"] as const,
  teams: (clubId?: string) => ["teams", { clubId }] as const,
  branding: (clubId: string) => ["branding", clubId] as const,
  players: {
    all: ["players"] as const,
    list: (filters: PlayerFilters) => ["players", "list", filters] as const,
    detail: (id: string) => ["players", "detail", id] as const,
  },
  content: {
    all: ["content"] as const,
    list: (filters: ContentFilters) => ["content", "list", filters] as const,
    detail: (id: string) => ["content", "detail", id] as const,
  },
  assistant: ["assistant"] as const,
  media: (clubId: string, purpose?: string) => ["media", clubId, purpose] as const,
  competitions: {
    all: ["competitions"] as const,
    catalogue: ["competitions", "catalogue"] as const,
    entries: (clubId: string) => ["competitions", "entries", clubId] as const,
    table: (seasonId: string) => ["competitions", "table", seasonId] as const,
    directory: (seasonId: string | null, q: string) =>
      ["competitions", "directory", seasonId, q] as const,
  },
  shop: {
    all: ["shop"] as const,
    products: (clubId: string) => ["shop", "products", clubId] as const,
    orders: (clubId: string, status?: string) => ["shop", "orders", clubId, status] as const,
  },
  matches: {
    all: ["matches"] as const,
    list: (clubId: string, upcoming?: boolean) => ["matches", clubId, upcoming] as const,
  },
  sports: ["sports"] as const,
  marketing: {
    templates: (clubId?: string) => ["email-templates", clubId] as const,
    preview: (id: string) => ["email-templates", id, "preview"] as const,
    campaigns: (clubId?: string) => ["campaigns", clubId] as const,
    audience: (clubId: string, pool: string) => ["campaigns", "audience", clubId, pool] as const,
  },
  analytics: (clubId: string | undefined, range: string) =>
    ["analytics", clubId, range] as const,
  teamStaff: (teamId: string) => ["team-staff", teamId] as const,
  staff: {
    all: ["staff"] as const,
    roles: (clubId?: string, teamId?: string) => ["staff", "roles", clubId, teamId] as const,
  },
};

export function useMe(): UseQueryResult<MeResponse, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api.get<MeResponse>("/api/v1/me"),
    staleTime: 60_000,
    // A 401 means the session is gone; retrying just delays the redirect.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}

export function useTeams(clubId?: string): UseQueryResult<Team[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.teams(clubId),
    queryFn: () => api.get<Team[]>("/api/v1/teams", { club_id: clubId }),
    staleTime: 300_000,
  });
}

export function usePlayers(
  filters: PlayerFilters,
): UseQueryResult<Page<PlayerSummary>, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.players.list(filters),
    queryFn: () =>
      api.get<Page<PlayerSummary>>("/api/v1/players", {
        ...filters,
        with_total: filters.with_total ?? true,
      }),
    placeholderData: (previous) => previous, // keeps the table stable while paging
  });
}

export function usePlayer(id: string): UseQueryResult<PlayerDetail, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.players.detail(id),
    queryFn: () => api.get<PlayerDetail>(`/api/v1/players/${id}`),
    enabled: Boolean(id),
  });
}

export function useBranding(clubId: string): UseQueryResult<Branding, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.branding(clubId),
    queryFn: () => api.get<Branding>(`/api/v1/clubs/${clubId}/branding`),
    enabled: Boolean(clubId),
  });
}

export function useUpdateBranding(
  clubId: string,
): UseMutationResult<Branding, ApiError, BrandingUpdate> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.put<Branding>(`/api/v1/clubs/${clubId}/branding`, input),
    onSuccess: (branding) => {
      queryClient.setQueryData(queryKeys.branding(clubId), branding);
      // The shell reads club branding from /me, so it must refetch to repaint.
      void queryClient.invalidateQueries({ queryKey: queryKeys.me });
    },
  });
}

export interface CreatePlayerInput {
  club_id: string;
  first_name: string;
  last_name: string;
  birth_date?: string | null;
  team_id?: string | null;
  shirt_number?: number | null;
  primary_position?: string | null;
  preferred_foot?: string | null;
}

export function useCreatePlayer(): UseMutationResult<
  PlayerDetail,
  ApiError,
  CreatePlayerInput
> {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input) =>
      // A retried create must not produce two players.
      api.post<PlayerDetail>("/api/v1/players", input, crypto.randomUUID()),
    onSuccess: () => {
      // Precise, not blanket: only the player collection is stale.
      void queryClient.invalidateQueries({ queryKey: queryKeys.players.all });
    },
  });
}

// --- Newsroom --------------------------------------------------------------

export function useContentList(
  filters: ContentFilters,
): UseQueryResult<Page<ContentSummary>, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.content.list(filters),
    queryFn: () =>
      api.get<Page<ContentSummary>>("/api/v1/content", {
        ...filters,
        with_total: filters.with_total ?? true,
      }),
    placeholderData: (previous) => previous,
  });
}

export function useContent(id: string | null): UseQueryResult<ContentDetail, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.content.detail(id ?? ""),
    queryFn: () => api.get<ContentDetail>(`/api/v1/content/${id}`),
    enabled: Boolean(id),
  });
}

export function useCreateContent(): UseMutationResult<
  ContentDetail,
  ApiError,
  ContentCreate
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) =>
      // A double-submitted "new article" must not create two drafts.
      api.post<ContentDetail>("/api/v1/content", input, crypto.randomUUID()),
    onSuccess: (item) => {
      queryClient.setQueryData(queryKeys.content.detail(item.id), item);
      void queryClient.invalidateQueries({ queryKey: queryKeys.content.all });
    },
  });
}

export function useSaveTranslation(
  itemId: string,
): UseMutationResult<ContentDetail, ApiError, TranslationInput> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) =>
      api.put<ContentDetail>(
        `/api/v1/content/${itemId}/translations/${input.locale}`,
        input,
      ),
    onSuccess: (item) => {
      queryClient.setQueryData(queryKeys.content.detail(itemId), item);
      void queryClient.invalidateQueries({ queryKey: queryKeys.content.all });
    },
  });
}

export interface TransitionInput {
  status: ContentStatus;
  scheduled_for?: string | null;
}

export function useTransitionContent(
  itemId: string,
): UseMutationResult<ContentDetail, ApiError, TransitionInput> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) =>
      api.post<ContentDetail>(`/api/v1/content/${itemId}/status`, input),
    onSuccess: (item) => {
      queryClient.setQueryData(queryKeys.content.detail(itemId), item);
      void queryClient.invalidateQueries({ queryKey: queryKeys.content.all });
    },
  });
}

export function useUpdateContentItem(): UseMutationResult<
  ContentDetail,
  ApiError,
  { id: string; changes: { cover_media_id?: string | null; is_pinned?: boolean } }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }) =>
      api.patch<ContentDetail>(`/api/v1/content/${id}`, changes),
    onSuccess: (item) => {
      queryClient.setQueryData(queryKeys.content.detail(item.id), item);
      void queryClient.invalidateQueries({ queryKey: queryKeys.content.all });
    },
  });
}

export function useDeleteContent(): UseMutationResult<void, ApiError, string> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete<void>(`/api/v1/content/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.content.all });
    },
  });
}

// --- Writing assistant -----------------------------------------------------

export function useAssistant(): UseQueryResult<AssistantStatus, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.assistant,
    queryFn: () => api.get<AssistantStatus>("/api/v1/ai/assistant"),
    staleTime: 60_000,
  });
}

export function usePolish(): UseMutationResult<
  PolishSuggestion,
  ApiError,
  AssistRequest
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.post<PolishSuggestion>("/api/v1/ai/polish", input),
    // The allowance is spent whether or not the editor keeps the suggestion,
    // so the counter must refresh either way.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assistant });
    },
  });
}

export function useHeadlines(): UseMutationResult<
  HeadlineSuggestion,
  ApiError,
  AssistRequest
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.post<HeadlineSuggestion>("/api/v1/ai/headlines", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assistant });
    },
  });
}

export function useRecordOutcome(): UseMutationResult<
  void,
  ApiError,
  { usageId: string; accepted: boolean }
> {
  const api = useApi();
  return useMutation({
    // Fire-and-forget telemetry: whether the editor kept the suggestion is the
    // only honest measure of the feature, but failing to record it must never
    // block the editor's actual work.
    mutationFn: ({ usageId, accepted }) =>
      api.post<void>(`/api/v1/ai/usage/${usageId}/outcome`, { accepted }),
  });
}

// --- Media -----------------------------------------------------------------

export function useMedia(
  clubId: string,
  purpose?: MediaPurpose,
): UseQueryResult<MediaAsset[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.media(clubId, purpose),
    queryFn: () => api.get<MediaAsset[]>("/api/v1/media", { club_id: clubId, purpose }),
    enabled: Boolean(clubId),
  });
}

export interface UploadInput {
  clubId: string;
  purpose: MediaPurpose;
  file: File;
  altText?: string;
}

export function useUploadMedia(): UseMutationResult<MediaAsset, ApiError, UploadInput> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clubId, purpose, file, altText }) => {
      const form = new FormData();
      form.set("club_id", clubId);
      form.set("purpose", purpose);
      form.set("file", file);
      if (altText) form.set("alt_text", altText);
      return api.upload<MediaAsset>("/api/v1/media", form);
    },
    onSuccess: (asset) => {
      void queryClient.invalidateQueries({ queryKey: ["media", asset.club_id] });
    },
  });
}

export function useSetAltText(): UseMutationResult<
  MediaAsset,
  ApiError,
  { assetId: string; altText: string }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, altText }) =>
      api.patch<MediaAsset>(`/api/v1/media/${assetId}`, { alt_text: altText }),
    onSuccess: (asset) => {
      void queryClient.invalidateQueries({ queryKey: ["media", asset.club_id] });
    },
  });
}

/**
 * Where the picture is, so every frame crops around the same point.
 *
 * Separate from the alt text because they are set from different controls and
 * neither should have to send the other's current value back. Both coordinates
 * always go together — the server refuses half a focal point.
 */
export function useSetFocalPoint(): UseMutationResult<
  MediaAsset,
  ApiError,
  { assetId: string; x: number; y: number }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, x, y }) =>
      api.patch<MediaAsset>(`/api/v1/media/${assetId}`, { focal_x: x, focal_y: y }),
    onSuccess: (asset) => {
      void queryClient.invalidateQueries({ queryKey: ["media", asset.club_id] });
    },
  });
}

export function useDeleteMedia(): UseMutationResult<
  void,
  ApiError,
  { assetId: string; clubId: string }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId }) => api.delete<void>(`/api/v1/media/${assetId}`),
    onSuccess: (_result, { clubId }) => {
      void queryClient.invalidateQueries({ queryKey: ["media", clubId] });
    },
  });
}

// --- Sign-up ---------------------------------------------------------------
//
// Unauthenticated, so these are the only hooks that work before there is a
// session. They still go through the same client — one place knows how to talk
// to the API, whether or not anyone is signed in.

export function usePlatformLocales(): UseQueryResult<PlatformLocale[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["signup", "locales"],
    queryFn: () => api.get<PlatformLocale[]>("/api/v1/public/register/languages"),
    staleTime: Infinity,
  });
}

/** How this club's results feed is set up. */
export function useFeed(clubId: string): UseQueryResult<FeedSettings, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["feed", "settings", clubId],
    queryFn: () => api.get<FeedSettings>(`/api/v1/clubs/${clubId}/feed`),
    enabled: Boolean(clubId),
  });
}

/** Point the feed at a club in the provider's catalogue, or turn it off. */
export function useUpdateFeed(
  clubId: string,
): UseMutationResult<FeedSettings, ApiError, FeedUpdate> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.put<FeedSettings>(`/api/v1/clubs/${clubId}/feed`, input),
    onSuccess: (settings) => {
      queryClient.setQueryData(["feed", "settings", clubId], settings);
    },
  });
}

/** Bring in the provider's squad for one of our teams. */
export function useImportSquad(
  clubId: string,
): UseMutationResult<{ created: number; skipped: number; notes: string[] }, ApiError, string> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (teamId) =>
      api.post<{ created: number; skipped: number; notes: string[] }>(
        `/api/v1/clubs/${clubId}/feed/squad?team_id=${encodeURIComponent(teamId)}`,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["players"] });
      void queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
  });
}

/** Fetch now rather than waiting for the scheduler's next turn. */
export function useSyncFeed(clubId: string): UseMutationResult<unknown, ApiError, void> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<unknown>(`/api/v1/clubs/${clubId}/feed/sync`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["feed", "settings", clubId] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.competitions.all });
    },
  });
}

/**
 * The divisions the results provider covers in a country.
 *
 * Cached hard: this is a third party's catalogue, it changes a few times a
 * year, and every call spends from an allowance shared by every club on the
 * platform.
 */
export function useProviderLeagues(
  country: string,
  enabled = true,
): UseQueryResult<ProviderCatalogue, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["feed", "leagues", country],
    queryFn: () => api.get<ProviderCatalogue>("/api/v1/feed/leagues", { country }),
    staleTime: 60 * 60 * 1000,
    enabled,
  });
}

/** Everyone in one division that season, for the club to point at itself. */
export function useProviderLeagueTeams(
  leagueId: string,
  season: number | null,
): UseQueryResult<ProviderTeam[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["feed", "leagues", leagueId, "teams", season],
    queryFn: () =>
      api.get<ProviderTeam[]>(`/api/v1/feed/leagues/${leagueId}/teams`, {
        season: season ?? undefined,
      }),
    staleTime: 60 * 60 * 1000,
    enabled: Boolean(leagueId && season),
  });
}

export function useSlugCheck(name: string): UseQueryResult<SlugCheck, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["signup", "slug", name],
    queryFn: () => api.get<SlugCheck>("/api/v1/public/register/slug", { name }),
    // Below three characters the answer is always "no"; asking wastes a round
    // trip on every keystroke of someone typing their club's name.
    enabled: name.trim().length >= 3,
    staleTime: 30_000,
  });
}

export function useSignUp(): UseMutationResult<SignUpResult, ApiError, SignUpInput> {
  const api = useApi();
  return useMutation({
    mutationFn: (input) => api.post<SignUpResult>("/api/v1/public/register", input),
  });
}

// --- Competitions and fixtures ---------------------------------------------

/** The platform's competition catalogue. Reference data: cached hard. */
export function useCompetitions(): UseQueryResult<Competition[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.competitions.catalogue,
    queryFn: () => api.get<Competition[]>("/api/v1/competitions"),
    staleTime: 3_600_000,
  });
}

export function useCompetitionEntries(
  clubId: string,
): UseQueryResult<CompetitionEntry[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.competitions.entries(clubId),
    queryFn: () =>
      api.get<CompetitionEntry[]>("/api/v1/competitions/entries", { club_id: clubId }),
    enabled: Boolean(clubId),
  });
}

export function useJoinCompetition(): UseMutationResult<
  JoinedCompetition,
  ApiError,
  JoinCompetitionInput
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.post<JoinedCompetition>("/api/v1/competitions/join", input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.competitions.all });
    },
  });
}

/**
 * Opponents. Scoped to a season when there is one, because the club a fixture
 * form wants is nearly always one this club is already in a division with.
 */
export function useDirectoryClubs(
  seasonId: string | null,
  search: string,
): UseQueryResult<DirectoryClub[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.competitions.directory(seasonId, search),
    queryFn: () =>
      api.get<DirectoryClub[]>("/api/v1/directory/clubs", {
        q: search || undefined,
        season_id: seasonId ?? undefined,
      }),
    staleTime: 60_000,
  });
}

export function useAddDirectoryClub(): UseMutationResult<
  DirectoryClub,
  ApiError,
  { name: string; city?: string }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.post<DirectoryClub>("/api/v1/directory/clubs", input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.competitions.all });
    },
  });
}

export function useMatches(
  clubId: string,
  upcoming?: boolean,
): UseQueryResult<Match[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.matches.list(clubId, upcoming),
    queryFn: () =>
      api.get<Match[]>("/api/v1/matches", { club_id: clubId, upcoming }),
    enabled: Boolean(clubId),
  });
}

export function useTable(seasonId: string | null): UseQueryResult<TableRow[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.competitions.table(seasonId ?? ""),
    queryFn: () => api.get<TableRow[]>(`/api/v1/competitions/${seasonId}/table`),
    enabled: Boolean(seasonId),
  });
}

export function useCreateMatch(): UseMutationResult<Match, ApiError, MatchCreate> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) =>
      api.post<Match>("/api/v1/matches", input, crypto.randomUUID()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.matches.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.competitions.all });
    },
  });
}

export function useUpdateMatch(
  clubId: string,
): UseMutationResult<Match, ApiError, { id: string; changes: MatchUpdate }> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }) =>
      api.patch<Match>(`/api/v1/matches/${id}?club_id=${clubId}`, changes),
    onSuccess: () => {
      // A result changes the table as well as the fixture.
      void queryClient.invalidateQueries({ queryKey: queryKeys.matches.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.competitions.all });
    },
  });
}

// --- Squads ----------------------------------------------------------------

export function useCreateTeam(): UseMutationResult<Team, ApiError, TeamInput> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.post<Team>("/api/v1/teams", input, crypto.randomUUID()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
  });
}

export function useUpdateTeam(): UseMutationResult<
  Team,
  ApiError,
  { id: string; changes: TeamUpdate }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }) => api.patch<Team>(`/api/v1/teams/${id}`, changes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["teams"] });
      // An archived team disappears from the squad shown on a player row.
      void queryClient.invalidateQueries({ queryKey: queryKeys.players.all });
    },
  });
}

/**
 * Remove a player from the club.
 *
 * Not the same as a departure. A player who has left is `DEPARTED` and stays
 * in the archive — they played, and the results they were part of are real.
 * This is for a record that should never have existed.
 */
export function useDeletePlayer(): UseMutationResult<void, ApiError, string> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete<void>(`/api/v1/players/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["players"] });
      void queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
  });
}

export function useUpdatePlayer(): UseMutationResult<
  PlayerDetail,
  ApiError,
  { id: string; changes: PlayerUpdate }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }) =>
      api.patch<PlayerDetail>(`/api/v1/players/${id}`, changes),
    onSuccess: (player) => {
      queryClient.setQueryData(queryKeys.players.detail(player.id), player);
      void queryClient.invalidateQueries({ queryKey: queryKeys.players.list({}) });
    },
  });
}

/** Moving a squad or changing a number: a new registration, not an edit. */
export function useChangeRegistration(): UseMutationResult<
  PlayerDetail,
  ApiError,
  { id: string; change: RegistrationChange }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, change }) =>
      api.put<PlayerDetail>(`/api/v1/players/${id}/registration`, change),
    onSuccess: (player) => {
      queryClient.setQueryData(queryKeys.players.detail(player.id), player);
      void queryClient.invalidateQueries({ queryKey: queryKeys.players.all });
    },
  });
}

// --- Shop -------------------------------------------------------------------

export function useProducts(clubId: string): UseQueryResult<Product[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.shop.products(clubId),
    queryFn: () => api.get<Product[]>("/api/v1/products", { club_id: clubId }),
    enabled: Boolean(clubId),
  });
}

export function useCreateProduct(): UseMutationResult<Product, ApiError, ProductInput> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) =>
      api.post<Product>("/api/v1/products", input, crypto.randomUUID()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.shop.all });
    },
  });
}

export function useUpdateProduct(): UseMutationResult<
  Product,
  ApiError,
  { id: string; changes: ProductChanges }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }) =>
      api.patch<Product>(`/api/v1/products/${id}`, changes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.shop.all });
    },
  });
}

export function useDeleteProduct(): UseMutationResult<void, ApiError, string> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/products/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.shop.all });
    },
  });
}

export function useShopOrders(
  clubId: string,
  status?: string,
): UseQueryResult<ShopOrder[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.shop.orders(clubId, status),
    queryFn: () =>
      api.get<ShopOrder[]>("/api/v1/orders", { club_id: clubId, status }),
    enabled: Boolean(clubId),
    // Someone is standing at the counter with a reference number.
    refetchInterval: 60_000,
  });
}

export function useSetOrderStatus(
  clubId: string,
): UseMutationResult<ShopOrder, ApiError, { id: string; status: "COLLECTED" | "CANCELLED" }> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }) =>
      api.post<ShopOrder>(`/api/v1/orders/${id}/status?club_id=${clubId}`, { status }),
    onSuccess: () => {
      // Cancelling puts stock back, so the catalogue is stale too.
      void queryClient.invalidateQueries({ queryKey: queryKeys.shop.all });
    },
  });
}

// --- The super-admin console ------------------------------------------------

export const platformKeys = {
  all: ["platform"] as const,
  tenants: (q: string) => ["platform", "tenants", q] as const,
  plans: ["platform", "plans"] as const,
  competitions: ["platform", "competitions"] as const,
};

export function usePlatformTenants(
  search = "",
): UseQueryResult<PlatformTenant[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.tenants(search),
    queryFn: () =>
      api.get<PlatformTenant[]>("/api/v1/platform/tenants", { q: search || undefined }),
  });
}

export function usePlatformPlans(): UseQueryResult<PlatformPlan[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.plans,
    queryFn: () => api.get<PlatformPlan[]>("/api/v1/platform/plans"),
    staleTime: 3_600_000,
  });
}

export function useSetTenantPlan(): UseMutationResult<
  PlatformTenant,
  ApiError,
  { id: string; plan_key: string; status?: string }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, plan_key, status }) =>
      api.put<PlatformTenant>(`/api/v1/platform/tenants/${id}/subscription`, {
        plan_key,
        status: status ?? "ACTIVE",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: platformKeys.all });
    },
  });
}

export function useUpdatePlatformTenant(): UseMutationResult<
  PlatformTenant,
  ApiError,
  { id: string; changes: { status?: string; suspended_reason?: string | null } }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }) =>
      api.patch<PlatformTenant>(`/api/v1/platform/tenants/${id}`, changes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: platformKeys.all });
    },
  });
}

export function usePlatformCompetitions(): UseQueryResult<
  PlatformCompetition[],
  ApiError
> {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.competitions,
    queryFn: () => api.get<PlatformCompetition[]>("/api/v1/platform/competitions"),
  });
}

export function useSaveCompetition(): UseMutationResult<
  PlatformCompetition,
  ApiError,
  { id?: string; input: Omit<PlatformCompetition, "id" | "seasons"> }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }) =>
      id
        ? api.patch<PlatformCompetition>(`/api/v1/platform/competitions/${id}`, input)
        : api.post<PlatformCompetition>("/api/v1/platform/competitions", input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: platformKeys.competitions });
    },
  });
}


/* --- staff ----------------------------------------------------------------
 *
 * Granting a role is a sensitive permission, so every mutation here can come
 * back 401 STEP_UP_REQUIRED even for somebody who holds the permission. That
 * is not a session failure and must not be treated as one — the screen asks
 * for a second factor instead.
 */

export function useStaff(): UseQueryResult<StaffMember[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.staff.all,
    queryFn: () => api.get<StaffMember[]>("/api/v1/staff"),
  });
}

export function useStaffRoles(
  clubId?: string,
  teamId?: string,
): UseQueryResult<StaffRole[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.staff.roles(clubId, teamId),
    queryFn: () =>
      api.get<StaffRole[]>("/api/v1/staff/roles", {
        ...(clubId ? { club_id: clubId } : {}),
        ...(teamId ? { team_id: teamId } : {}),
      }),
  });
}

export function useInviteStaff(): UseMutationResult<StaffMember, ApiError, StaffInvite> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) =>
      api.post<StaffMember>("/api/v1/staff", input, crypto.randomUUID()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.staff.all });
    },
  });
}

export function useChangeStaffRole(): UseMutationResult<
  StaffMember,
  ApiError,
  { userId: string; role: string; club_id?: string | null; team_id?: string | null }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, ...body }) =>
      api.put<StaffMember>(`/api/v1/staff/${userId}/role`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.staff.all });
    },
  });
}

export function useRemoveStaffAccount(): UseMutationResult<void, ApiError, string> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId) => api.delete(`/api/v1/staff/${userId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.staff.all });
    },
  });
}

export function useResendInvitation(): UseMutationResult<void, ApiError, string> {
  const api = useApi();
  return useMutation({
    mutationFn: (userId) => api.post<void>(`/api/v1/staff/${userId}/invitation`, {}),
  });
}

export function useRemoveStaff(): UseMutationResult<void, ApiError, string> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId) => api.delete(`/api/v1/staff/${userId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.staff.all });
    },
  });
}

/* --- a team's touchline ---------------------------------------------------- */

export function useTeamStaff(teamId: string | null): UseQueryResult<TeamStaffMember[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.teamStaff(teamId ?? ""),
    queryFn: () => api.get<TeamStaffMember[]>(`/api/v1/teams/${teamId}/staff`),
    enabled: Boolean(teamId),
  });
}

export function useAddTeamStaff(): UseMutationResult<
  TeamStaffMember,
  ApiError,
  { teamId: string; input: TeamStaffInput }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teamId, input }) =>
      api.post<TeamStaffMember>(`/api/v1/teams/${teamId}/staff`, input, crypto.randomUUID()),
    onSuccess: (_row, { teamId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamStaff(teamId) });
    },
  });
}

export function useUpdateTeamStaff(): UseMutationResult<
  TeamStaffMember,
  ApiError,
  { teamId: string; staffId: string; changes: Partial<TeamStaffInput> }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teamId, staffId, changes }) =>
      api.patch<TeamStaffMember>(`/api/v1/teams/${teamId}/staff/${staffId}`, changes),
    onSuccess: (_row, { teamId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamStaff(teamId) });
    },
  });
}

export function useRemoveTeamStaff(): UseMutationResult<
  void,
  ApiError,
  { teamId: string; staffId: string }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teamId, staffId }) => api.delete(`/api/v1/teams/${teamId}/staff/${staffId}`),
    onSuccess: (_void, { teamId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamStaff(teamId) });
    },
  });
}

/**
 * The sports the platform supports.
 *
 * Reference data that never changes between deploys, so it is cached hard —
 * asking on every render of a team dialog would be one request per keystroke
 * for a list that is the same all day.
 */
export function useSports(): UseQueryResult<Sport[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.sports,
    queryFn: () => api.get<Sport[]>("/api/v1/sports"),
    staleTime: 60 * 60 * 1000,
  });
}

/**
 * The whole analytics screen in one request.
 *
 * Refetched on a timer because the live-visitor count is on it, and a number
 * labelled "now" that is four minutes old is a lie. Thirty seconds is often
 * enough to feel live and rare enough that a club leaving the tab open all
 * afternoon does not hammer the database.
 */
export function useAnalytics(
  range: AnalyticsRange,
  clubId?: string,
): UseQueryResult<AnalyticsOverview, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.analytics(clubId, range),
    queryFn: () =>
      api.get<AnalyticsOverview>("/api/v1/analytics/overview", {
        range,
        ...(clubId ? { club_id: clubId } : {}),
      }),
    refetchInterval: 30_000,
  });
}

/* --- email marketing ------------------------------------------------------- */

export function useEmailTemplates(clubId?: string): UseQueryResult<EmailTemplate[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.marketing.templates(clubId),
    queryFn: () =>
      api.get<EmailTemplate[]>("/api/v1/email-templates", clubId ? { club_id: clubId } : {}),
  });
}

export function useEmailPreview(id: string | null): UseQueryResult<EmailPreview, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.marketing.preview(id ?? ""),
    queryFn: () => api.get<EmailPreview>(`/api/v1/email-templates/${id}/preview`),
    enabled: Boolean(id),
  });
}

export function useCreateEmailTemplate(): UseMutationResult<
  EmailTemplate,
  ApiError,
  EmailTemplateInput
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) =>
      api.post<EmailTemplate>("/api/v1/email-templates", input, crypto.randomUUID()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["email-templates"] });
    },
  });
}

export function useUpdateEmailTemplate(): UseMutationResult<
  EmailTemplate,
  ApiError,
  { id: string; changes: EmailTemplateChanges }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }) =>
      api.patch<EmailTemplate>(`/api/v1/email-templates/${id}`, changes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["email-templates"] });
    },
  });
}

export function useCampaigns(clubId?: string): UseQueryResult<Campaign[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.marketing.campaigns(clubId),
    queryFn: () => api.get<Campaign[]>("/api/v1/campaigns", clubId ? { club_id: clubId } : {}),
  });
}

/**
 * How many people a campaign would reach, before anybody presses send.
 *
 * Asked as the club changes the audience, because "you are about to write to
 * 412 people" is the sentence that stops a mistake.
 */
export function useAudienceSize(
  clubId: string | undefined,
  pool: CampaignAudience,
): UseQueryResult<AudienceSize, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.marketing.audience(clubId ?? "", pool),
    queryFn: () => api.get<AudienceSize>("/api/v1/campaigns/audience", { club_id: clubId, pool }),
    enabled: Boolean(clubId),
  });
}

export function useCreateCampaign(): UseMutationResult<Campaign, ApiError, CampaignInput> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input) => api.post<Campaign>("/api/v1/campaigns", input, crypto.randomUUID()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useSendCampaign(): UseMutationResult<Campaign, ApiError, string> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.post<Campaign>(`/api/v1/campaigns/${id}/send`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useSendTestEmail(): UseMutationResult<
  void,
  ApiError,
  { id: string; to: string }
> {
  const api = useApi();
  return useMutation({
    mutationFn: ({ id, to }) => api.post<void>(`/api/v1/campaigns/${id}/test`, { to }),
  });
}

// --- Card payments ----------------------------------------------------------

/**
 * A tenant's card gateways.
 *
 * Reading is not sensitive — no secret comes back — so this behaves like any
 * other query. Writing is: the mutations below answer 401 `STEP_UP_REQUIRED`
 * to somebody who has not proved themselves recently, which `useStepUp` in the
 * admin application turns into a prompt and a retry.
 */
export function usePaymentGateways(): UseQueryResult<PaymentGateway[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["payment-gateways"],
    queryFn: () => api.get<PaymentGateway[]>("/api/v1/payments/settings"),
  });
}

export function useSavePaymentGateway(): UseMutationResult<
  PaymentGateway,
  ApiError,
  { provider: string; settings: PaymentGatewayInput }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, settings }) =>
      api.put<PaymentGateway>(`/api/v1/payments/settings/${provider}`, settings),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["payment-gateways"] });
    },
  });
}

export function useCheckPaymentGateway(): UseMutationResult<
  PaymentGatewayCheck,
  ApiError,
  { provider: string }
> {
  const api = useApi();
  return useMutation({
    mutationFn: ({ provider }) =>
      api.post<PaymentGatewayCheck>(`/api/v1/payments/settings/${provider}/test`, {}),
  });
}

/** Every call made to a gateway, newest first. The evidence for a dispute. */
export function usePaymentCalls(filters: {
  order_ref?: string;
  failed_only?: boolean;
  limit?: number;
}): UseQueryResult<Page<PaymentCall>, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["payment-calls", filters],
    queryFn: () =>
      api.get<Page<PaymentCall>>("/api/v1/payments/calls", {
        ...(filters.order_ref ? { order_ref: filters.order_ref } : {}),
        ...(filters.failed_only ? { failed_only: "true" } : {}),
        limit: String(filters.limit ?? 50),
      }),
  });
}

export function usePaymentCall(
  callId: string | null,
): UseQueryResult<PaymentCallDetail, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ["payment-call", callId],
    queryFn: () => api.get<PaymentCallDetail>(`/api/v1/payments/calls/${callId}`),
    enabled: Boolean(callId),
  });
}

// --- stadium & ticketing ---------------------------------------------------

/**
 * Query keys for the ticketing module.
 *
 * Deliberately nested under the thing they belong to, so that publishing a
 * configuration or holding a seat can invalidate exactly what changed. A flat
 * `["ticketing"]` key would refetch a thirty-thousand-seat layout every time
 * somebody blocked one seat.
 */
export const ticketingKeys = {
  venues: (clubId?: string) => ["ticketing", "venues", { clubId }] as const,
  configurations: (venueId: string) => ["ticketing", "configurations", venueId] as const,
  layout: (configurationId: string) => ["ticketing", "layout", configurationId] as const,
  review: (configurationId: string) => ["ticketing", "review", configurationId] as const,
  priceZones: (configurationId: string) => ["ticketing", "zones", configurationId] as const,
  events: (clubId?: string) => ["ticketing", "events", { clubId }] as const,
  eventLayout: (eventId: string) => ["ticketing", "event-layout", eventId] as const,
  capacity: (eventId: string) => ["ticketing", "capacity", eventId] as const,
  pricing: (eventId: string) => ["ticketing", "pricing", eventId] as const,
  allocations: (eventId: string) => ["ticketing", "allocations", eventId] as const,
  tickets: (eventId: string) => ["ticketing", "tickets", eventId] as const,
  report: (eventId: string) => ["ticketing", "report", eventId] as const,
  ticketTypes: ["ticketing", "ticket-types"] as const,
  seasonProducts: (clubId?: string) => ["ticketing", "season-products", { clubId }] as const,
  gates: (eventId: string) => ["access", "gates", eventId] as const,
  live: (eventId: string) => ["access", "live", eventId] as const,
  devices: ["access", "devices"] as const,
};

export function useVenues(clubId?: string): UseQueryResult<Venue[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.venues(clubId),
    queryFn: () =>
      api.get<Venue[]>("/api/v1/ticketing/venues", clubId ? { club_id: clubId } : undefined),
  });
}

export function useVenueConfigurations(
  venueId: string | undefined,
): UseQueryResult<VenueConfiguration[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.configurations(venueId ?? ""),
    queryFn: () =>
      api.get<VenueConfiguration[]>(`/api/v1/ticketing/venues/${venueId}/configurations`),
    enabled: Boolean(venueId),
  });
}

export function useStadiumLayout(
  configurationId: string | undefined,
): UseQueryResult<StadiumLayout, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.layout(configurationId ?? ""),
    queryFn: () =>
      api.get<StadiumLayout>(`/api/v1/ticketing/configurations/${configurationId}/layout`),
    enabled: Boolean(configurationId),
  });
}

export function useConfigurationReview(
  configurationId: string | undefined,
): UseQueryResult<ConfigurationReview, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.review(configurationId ?? ""),
    queryFn: () =>
      api.get<ConfigurationReview>(
        `/api/v1/ticketing/configurations/${configurationId}/review`,
      ),
    enabled: Boolean(configurationId),
  });
}

export function usePublishConfiguration(): UseMutationResult<
  VenueConfiguration,
  ApiError,
  string
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (configurationId) =>
      api.post<VenueConfiguration>(
        `/api/v1/ticketing/configurations/${configurationId}/publish`,
        {},
      ),
    onSuccess: () => {
      // Publishing changes the configuration list, the review and what the
      // editor will accept, so the whole subtree goes.
      void queryClient.invalidateQueries({ queryKey: ["ticketing"] });
    },
  });
}

export function useForkConfiguration(): UseMutationResult<
  VenueConfiguration,
  ApiError,
  string
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (configurationId) =>
      api.post<VenueConfiguration>(
        `/api/v1/ticketing/configurations/${configurationId}/fork`,
        {},
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ticketing"] });
    },
  });
}

export function useGenerateSeats(): UseMutationResult<
  { seats: number },
  ApiError,
  { sectionId: string; plan: Record<string, unknown> }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sectionId, plan }) =>
      api.post<{ seats: number }>(`/api/v1/ticketing/sections/${sectionId}/seats`, plan),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ticketing"] });
    },
  });
}

export function useTicketedEvents(clubId?: string): UseQueryResult<TicketedEvent[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.events(clubId),
    queryFn: () =>
      api.get<TicketedEvent[]>(
        "/api/v1/ticketing/events",
        clubId ? { club_id: clubId } : undefined,
      ),
  });
}

export function useEventLayout(
  eventId: string | undefined,
): UseQueryResult<EventLayout, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.eventLayout(eventId ?? ""),
    queryFn: () => api.get<EventLayout>(`/api/v1/ticketing/events/${eventId}/layout`),
    enabled: Boolean(eventId),
  });
}

export function useEventCapacity(
  eventId: string | undefined,
): UseQueryResult<EventCapacity, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.capacity(eventId ?? ""),
    queryFn: () => api.get<EventCapacity>(`/api/v1/ticketing/events/${eventId}/capacity`),
    enabled: Boolean(eventId),
  });
}

export function useEventReport(
  eventId: string | undefined,
): UseQueryResult<EventReport, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.report(eventId ?? ""),
    queryFn: () => api.get<EventReport>(`/api/v1/ticketing/events/${eventId}/report`),
    enabled: Boolean(eventId),
  });
}

export function usePricingMatrix(
  eventId: string | undefined,
): UseQueryResult<PricingMatrix, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.pricing(eventId ?? ""),
    queryFn: () => api.get<PricingMatrix>(`/api/v1/ticketing/events/${eventId}/pricing`),
    enabled: Boolean(eventId),
  });
}

export function useSaveEventPricing(): UseMutationResult<
  { rules: number },
  ApiError,
  { eventId: string; rules: Record<string, unknown>[] }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ eventId, rules }) =>
      api.put<{ rules: number }>(`/api/v1/ticketing/events/${eventId}/pricing`, rules),
    onSuccess: (_data, { eventId }) => {
      void queryClient.invalidateQueries({ queryKey: ticketingKeys.pricing(eventId) });
    },
  });
}

export function usePublishEvent(): UseMutationResult<
  { id: string; status: string },
  ApiError,
  string
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (eventId) =>
      api.post<{ id: string; status: string }>(
        `/api/v1/ticketing/events/${eventId}/publish`,
        {},
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ticketing"] });
    },
  });
}

export function useAllocations(
  eventId: string | undefined,
): UseQueryResult<Allocation[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.allocations(eventId ?? ""),
    queryFn: () => api.get<Allocation[]>(`/api/v1/ticketing/events/${eventId}/allocations`),
    enabled: Boolean(eventId),
  });
}

export function useEventTickets(
  eventId: string | undefined,
): UseQueryResult<IssuedTicket[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.tickets(eventId ?? ""),
    queryFn: () => api.get<IssuedTicket[]>(`/api/v1/ticketing/events/${eventId}/tickets`),
    enabled: Boolean(eventId),
  });
}

export function useTicketTypes(): UseQueryResult<TicketType[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.ticketTypes,
    queryFn: () => api.get<TicketType[]>("/api/v1/ticketing/ticket-types"),
  });
}

export function useSeasonProducts(
  clubId?: string,
): UseQueryResult<SeasonProduct[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.seasonProducts(clubId),
    queryFn: () =>
      api.get<SeasonProduct[]>(
        "/api/v1/ticketing/season-products",
        clubId ? { club_id: clubId } : undefined,
      ),
  });
}

// --- access control ---------------------------------------------------------

export function useEventGates(
  eventId: string | undefined,
): UseQueryResult<EventGate[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.gates(eventId ?? ""),
    queryFn: () => api.get<EventGate[]>(`/api/v1/access/events/${eventId}/gates`),
    enabled: Boolean(eventId),
  });
}

/**
 * Live entry counts. Polled rather than pushed: a control room refreshing every
 * few seconds is enough, and a websocket for a number that changes at walking
 * pace is infrastructure nobody needs to operate.
 */
export function useLiveScans(
  eventId: string | undefined,
  options?: { refetchInterval?: number },
): UseQueryResult<ScanCounts, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: ticketingKeys.live(eventId ?? ""),
    queryFn: () => api.get<ScanCounts>(`/api/v1/access/events/${eventId}/live`),
    enabled: Boolean(eventId),
    refetchInterval: options?.refetchInterval ?? 5000,
  });
}

export function useValidateScan(): UseMutationResult<
  ScanVerdict,
  ApiError,
  {
    event_id: string;
    credential: string;
    gate_code?: string | null;
    idempotency_key?: string;
    operator_name?: string | null;
  }
> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => api.post<ScanVerdict>("/api/v1/access/scans/validate", payload),
    onSuccess: (_verdict, { event_id }) => {
      void queryClient.invalidateQueries({ queryKey: ticketingKeys.live(event_id) });
    },
  });
}

// --- stadium editing --------------------------------------------------------

/**
 * Everything below invalidates the whole `["ticketing"]` subtree on success.
 *
 * Coarse on purpose: adding a sector changes the layout, the review, the
 * capacity totals and what the publish button will accept, and working out
 * which of those to refetch is a correctness problem nobody should have to
 * solve at every call site. A stadium is edited a few dozen times in its life,
 * not a few dozen times a second.
 */
function useTicketingMutation<TResult, TInput>(
  request: (api: ApiClient, input: TInput) => Promise<TResult>,
): UseMutationResult<TResult, ApiError, TInput> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TInput) => request(api, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ticketing"] });
    },
  });
}

export function useCreateVenue(): UseMutationResult<Venue, ApiError, Record<string, unknown>> {
  return useTicketingMutation((api, input) => api.post<Venue>("/api/v1/ticketing/venues", input));
}

export function useUpdateVenue(): UseMutationResult<
  Venue,
  ApiError,
  { venueId: string; body: Record<string, unknown> }
> {
  return useTicketingMutation((api, input) =>
    api.patch<Venue>(`/api/v1/ticketing/venues/${input.venueId}`, input.body),
  );
}

export function useCreateConfiguration(): UseMutationResult<
  VenueConfiguration,
  ApiError,
  { venueId: string; body: Record<string, unknown> }
> {
  return useTicketingMutation((api, input) =>
    api.post<VenueConfiguration>(
      `/api/v1/ticketing/venues/${input.venueId}/configurations`,
      input.body,
    ),
  );
}

export function useCreateStand(): UseMutationResult<
  { id: string },
  ApiError,
  { configurationId: string; body: Record<string, unknown> }
> {
  return useTicketingMutation((api, input) =>
    api.post<{ id: string }>(
      `/api/v1/ticketing/configurations/${input.configurationId}/stands`,
      input.body,
    ),
  );
}

export function useDeleteStand(): UseMutationResult<void, ApiError, string> {
  return useTicketingMutation((api, standId) =>
    api.delete<void>(`/api/v1/ticketing/stands/${standId}`),
  );
}

export function useCreateSection(): UseMutationResult<
  { id: string },
  ApiError,
  { standId: string; body: Record<string, unknown> }
> {
  return useTicketingMutation((api, input) =>
    api.post<{ id: string }>(`/api/v1/ticketing/stands/${input.standId}/sections`, input.body),
  );
}

export function useDeleteSection(): UseMutationResult<void, ApiError, string> {
  return useTicketingMutation((api, sectionId) =>
    api.delete<void>(`/api/v1/ticketing/sections/${sectionId}`),
  );
}

export function useCreatePriceZone(): UseMutationResult<
  { id: string },
  ApiError,
  { configurationId: string; body: Record<string, unknown> }
> {
  return useTicketingMutation((api, input) =>
    api.post<{ id: string }>(
      `/api/v1/ticketing/configurations/${input.configurationId}/price-zones`,
      input.body,
    ),
  );
}

export function useCreateGate(): UseMutationResult<
  { id: string },
  ApiError,
  { configurationId: string; body: Record<string, unknown> }
> {
  return useTicketingMutation((api, input) =>
    api.post<{ id: string }>(
      `/api/v1/ticketing/configurations/${input.configurationId}/gates`,
      input.body,
    ),
  );
}

export function useUpdateGate(): UseMutationResult<
  { id: string },
  ApiError,
  { gateId: string; body: Record<string, unknown> }
> {
  return useTicketingMutation((api, input) =>
    api.put<{ id: string }>(`/api/v1/ticketing/gates/${input.gateId}`, input.body),
  );
}

export function useDeleteGate(): UseMutationResult<void, ApiError, string> {
  return useTicketingMutation((api, gateId) =>
    api.delete<void>(`/api/v1/ticketing/gates/${gateId}`),
  );
}

// --- matchday console -------------------------------------------------------

/**
 * Record something the league feed has not reported.
 *
 * Providers carry goals within a few minutes and cards late or not at all for
 * smaller divisions, so a club watching from the stand can put them in itself.
 * The server marks these `source: "CLUB"` and the sync leaves them alone.
 */
export function useAddMatchEvent(
  clubId: string,
): UseMutationResult<MatchEventEntry, ApiError, { matchId: string; event: MatchEventInput }> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ matchId, event }) =>
      api.post<MatchEventEntry>(
        `/api/v1/matches/${matchId}/events?club_id=${clubId}`,
        event,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.matches.all });
    },
  });
}

export function useDeleteMatchEvent(
  clubId: string,
): UseMutationResult<void, ApiError, { matchId: string; eventId: string }> {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ matchId, eventId }) =>
      api.delete<void>(`/api/v1/matches/${matchId}/events/${eventId}?club_id=${clubId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.matches.all });
    },
  });
}
