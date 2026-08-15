import {
  queryKeys,
  useMe,
  type ClubSummary,
  type MeResponse,
  type Workspace,
} from "@footbola/api-client";
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { useParams } from "react-router-dom";

import { LocaleProvider } from "./locale";

/**
 * Resolved session: the workspace you are in, and what you may do in it.
 *
 * One application at one address. The club slug in the URL says which club you
 * are working in, which is what makes a link to `/fcexample/players` mean the
 * same thing for everyone who can open it.
 *
 * The slug is a *routing* input, not an authorization one. It selects an entry
 * from the workspace list the API returned for this user; the resulting tenant
 * id then travels as `X-Tenant-Id`, which the API re-validates against live
 * memberships on every request. A slug typed by hand for a club the user
 * cannot reach resolves to nothing here and would be rejected there anyway.
 *
 * `can()` drives navigation and button visibility. That is presentation only —
 * every gated action is enforced server-side as well, and the permission
 * matrix suite asserts it. Hiding a button is not authorization.
 */

interface SessionState {
  me: MeResponse;
  /** The club whose slug is in the URL. */
  club: ClubSummary;
  workspace: Workspace;
  can: (permission: string) => boolean;
  /** Prefixes a path with the current club slug. */
  path: (to: string) => string;
}

const SessionContext = createContext<SessionState | null>(null);

const TENANT_KEY = "footbola.tenantId";
const CLUB_KEY = "footbola.clubSlug";

export function getStoredTenantId(): string | null {
  return window.localStorage.getItem(TENANT_KEY);
}

export function setStoredTenantId(tenantId: string): void {
  window.localStorage.setItem(TENANT_KEY, tenantId);
}

export function getStoredClubSlug(): string | null {
  return window.localStorage.getItem(CLUB_KEY);
}

export function setStoredClubSlug(slug: string): void {
  window.localStorage.setItem(CLUB_KEY, slug);
}

/** The workspace list, before a club has been chosen. */
export function useWorkspaces() {
  return useMe();
}

export function findWorkspace(
  me: MeResponse | undefined,
  slug: string | undefined,
): Workspace | undefined {
  if (!me || !slug) return undefined;
  return me.workspaces.find((workspace) => workspace.club.slug === slug);
}

export function applyBranding(club: ClubSummary): void {
  // Club branding is applied as CSS custom properties — no per-tenant build,
  // no theme-switch flash. The palette is derived server-side, so the admin
  // shell and the public site are themed from the same maths.
  const root = document.documentElement;
  for (const [token, value] of Object.entries(club.palette ?? {})) {
    root.style.setProperty(token, value);
  }
  if (club.color_primary) root.style.setProperty("--brand", club.color_primary);
}

export function SessionProvider({
  children,
  fallback,
}: {
  children: ReactNode;
  /** Rendered while resolving, and when the slug names no reachable club. */
  fallback: (state: {
    isLoading: boolean;
    error: Error | null;
    me: MeResponse | undefined;
    unknownSlug: string | undefined;
  }) => ReactNode;
}) {
  const { clubSlug } = useParams<{ clubSlug: string }>();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useMe();

  const workspace = findWorkspace(data, clubSlug);
  // `workspaces` spans every tenant, but `permissions` and `clubs` are resolved
  // for whichever tenant the request carried. Entering a club in a different
  // tenant therefore has to re-bootstrap, or the shell would render one club's
  // name with another club's permissions.
  const tenantMismatch =
    Boolean(workspace) && data?.active_tenant?.id !== workspace!.tenant_id;

  useEffect(() => {
    if (!workspace) return;
    setStoredTenantId(workspace.tenant_id);
    setStoredClubSlug(workspace.club.slug);
    applyBranding(workspace.club);
    if (tenantMismatch) void queryClient.invalidateQueries({ queryKey: queryKeys.me });
  }, [workspace, tenantMismatch, queryClient]);

  const value = useMemo<SessionState | null>(() => {
    if (!data || !workspace || tenantMismatch) return null;
    const granted = new Set(data.permissions);
    const prefix = `/${workspace.club.slug}`;
    return {
      me: data,
      club: workspace.club,
      workspace,
      can: (permission: string) => granted.has(permission),
      path: (to: string) => (to === "/" ? prefix : `${prefix}${to}`),
    };
  }, [data, workspace, tenantMismatch]);

  if (!value) {
    return (
      <>
        {fallback({
          isLoading: isLoading || tenantMismatch,
          error: error ?? null,
          me: data,
          unknownSlug: data && !workspace ? clubSlug : undefined,
        })}
      </>
    );
  }

  return (
    <SessionContext.Provider value={value}>
      <LocaleProvider tenantLocale={value.me.active_tenant?.default_locale}>
        {children}
      </LocaleProvider>
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside a <SessionProvider>");
  return context;
}

export function Can({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const { can } = useSession();
  return can(permission) ? <>{children}</> : null;
}
