import { ApiClient, ApiError, ApiProvider } from "@footbola/api-client";
import "@footbola/ui/tokens.css";
import { Button, Spinner, ToastProvider, TooltipProvider } from "@footbola/ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth, useTokenRef } from "./app/auth";
import { SessionProvider, getStoredTenantId } from "./app/session";
import { Shell } from "./app/shell";
import { ThemeProvider } from "./app/theme";
import { NewsEditorPage } from "./pages/news/editor";
import { NewsListPage } from "./pages/news/list";
import { NotFoundPage } from "./pages/not-found";
import { OverviewPage } from "./pages/overview";
import { PlayerDetailPage } from "./pages/player-detail";
import { PlayersPage } from "./pages/players";
import { AnalyticsPage } from "./pages/analytics";
import { MarketingPage } from "./pages/marketing";
import { SettingsPage } from "./pages/settings";
import { StaffPage } from "./pages/staff";
import { SignUpPage } from "./pages/sign-up";
import { WorkspacePicker } from "./pages/workspace-picker";
import { SitePage } from "./pages/site/site";
import { MatchesPage } from "./pages/matches/matches";
import { PlatformConsole } from "./pages/platform/console";
import { ShopPage } from "./pages/shop/shop";
import { TeamsPage } from "./pages/teams";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Retrying a 4xx just delays showing the user what went wrong.
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status < 500) && failureCount < 2,
    },
  },
});

function SignInScreen({ error }: { error?: Error | null }) {
  const { signIn } = useAuth();

  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden bg-nav-bg p-6">
      {/* Two soft brand-tinted washes. The sign-in screen is the one place the
          club's colour can be atmospheric rather than functional — there is no
          data on this page for it to compete with. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 -left-32 size-[32rem] rounded-full opacity-25 blur-[120px]"
        style={{ background: "var(--brand)" }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-40 -bottom-48 size-[36rem] rounded-full opacity-15 blur-[140px]"
        style={{ background: "var(--brand)" }}
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-8 text-center">
          <span
            aria-hidden
            className="mx-auto mb-5 grid size-12 place-items-center rounded-xl bg-brand text-sm font-bold text-brand-contrast shadow-lg"
          >
            FOS
          </span>
          <h1 className="text-2xl font-semibold text-nav-text">Football Club OS</h1>
          <p className="mt-1.5 text-sm text-nav-text-secondary">
            One place to run the club, the academy and the website.
          </p>
        </div>

        <div className="rounded-xl border border-nav-border bg-nav-surface p-6 shadow-xl">
          {error && (
            <p
              className="mb-4 rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger"
              role="alert"
            >
              {error.message}
            </p>
          )}
          <Button variant="primary" size="lg" className="w-full" onClick={() => void signIn()}>
            Sign in
          </Button>
          <p className="mt-4 text-center text-xs text-nav-text-secondary">
            You will be taken to your club's identity provider.
          </p>
        </div>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="grid min-h-screen place-items-center bg-bg">
      <div className="flex items-center gap-2.5 text-sm text-text-secondary">
        <Spinner />
        Loading…
      </div>
    </div>
  );
}

function Authenticated() {
  const { user, isLoading, error, signOut } = useAuth();
  const tokenRef = useTokenRef();

  const api = useMemo(
    () =>
      new ApiClient({
        baseUrl: import.meta.env.VITE_API_URL as string,
        getToken: () => tokenRef.current,
        getTenantId: () => getStoredTenantId(),
        onUnauthenticated: () => {
          // The session is gone server-side; clearing it locally keeps the UI
          // from looping on a token the API has already rejected.
          void signOut();
        },
      }),
    [tokenRef, signOut],
  );

  if (isLoading) return <Loading />;

  // Sign-up is reachable without a session, because its whole audience is
  // people who do not have one. It still needs the API client, so it sits
  // inside the provider rather than beside it.
  if (!user) {
    return (
      <ApiProvider value={api}>
        <Routes>
          <Route path="/signup" element={<SignUpPage />} />
          <Route path="*" element={<SignInScreen error={error} />} />
        </Routes>
      </ApiProvider>
    );
  }

  return (
    <ApiProvider value={api}>
      <Routes>
        {/* One host, two applications. `/` and `/pricing` are the marketing
            site and never reach this bundle — the proxy sends them to Next.
            What arrives here is the signed-in product:

              /signin           the entry point the marketing site links to
              /auth/callback    where the identity provider returns
              /platform/…       the super-admin console
              /<club-slug>/…    a club's workspace

            Club slugs share this namespace, which is why the API refuses to
            issue a slug that collides with any of the words above. */}
        <Route path="/auth/callback" element={<Loading />} />
        <Route path="/signin" element={<WorkspacePicker />} />
        <Route path="/signup" element={<WorkspacePicker />} />
        <Route path="/platform" element={<PlatformShell />} />
        <Route path="/:clubSlug/*" element={<Workspace />} />
        <Route path="*" element={<WorkspacePicker />} />
      </Routes>
    </ApiProvider>
  );
}

/**
 * The super-admin console.
 *
 * Outside `SessionProvider` on purpose: that provider resolves a club from the
 * slug in the URL, and a platform operator is in no club — asking it to would
 * bounce them to the workspace picker.
 */
function PlatformShell() {
  return (
    <div className="mx-auto min-h-screen max-w-6xl px-6 py-10">
      <PlatformConsole />
    </div>
  );
}

function Workspace() {
  return (
    <SessionProvider
      fallback={({ isLoading, unknownSlug }) =>
        isLoading ? <Loading /> : <WorkspacePicker unknownSlug={unknownSlug} />
      }
    >
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<OverviewPage />} />
          <Route path="players" element={<PlayersPage />} />
          <Route path="players/:playerId" element={<PlayerDetailPage />} />
          <Route path="teams" element={<TeamsPage />} />
          <Route path="matches" element={<MatchesPage />} />
          <Route path="news" element={<NewsListPage />} />
          <Route path="news/:itemId" element={<NewsEditorPage />} />
          <Route path="shop" element={<ShopPage />} />
          <Route path="site" element={<SitePage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="marketing" element={<MarketingPage />} />
          <Route path="staff" element={<StaffPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </SessionProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <TooltipProvider delayDuration={300}>
            <ToastProvider>
              <AuthProvider>
                <Authenticated />
              </AuthProvider>
            </ToastProvider>
          </TooltipProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
);
