import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

/**
 * OIDC Authorization Code + PKCE.
 *
 * The access token lives in memory only. Session continuity comes from the
 * refresh token, which oidc-client-ts keeps in session storage and rotates —
 * so closing the tab ends the session, and an XSS payload cannot lift a
 * long-lived credential out of localStorage.
 */

const settings = {
  authority: import.meta.env.VITE_OIDC_ISSUER as string,
  client_id: import.meta.env.VITE_OIDC_CLIENT_ID as string,
  redirect_uri: `${window.location.origin}/auth/callback`,
  // Back to the marketing site, not to a blank app shell. Someone who signs
  // out has left the product, and the product's front door is that page.
  post_logout_redirect_uri: window.location.origin,
  response_type: "code",
  scope: "openid profile email",
  automaticSilentRenew: true,
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
};

const manager = new UserManager(settings);

/**
 * The code exchange, held outside React.
 *
 * An authorization code is single-use. StrictMode mounts every effect twice in
 * development, and React may re-run an effect at any time in production, so an
 * exchange started from inside a component will be started twice — the first
 * succeeds, the second is refused with "Code not valid", and the user is left
 * looking at a 400 having apparently signed in.
 *
 * Memoising the *promise* rather than guarding with a boolean is what makes
 * this correct: the second caller waits on the same request instead of racing
 * a flag that has not been set yet.
 */
let pendingExchange: Promise<User> | null = null;

function exchangeCode(): Promise<User> {
  pendingExchange ??= manager.signinRedirectCallback();
  return pendingExchange;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  error: Error | null;
  token: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        if (window.location.pathname === "/auth/callback") {
          const signedIn = await exchangeCode();
          if (cancelled) return;
          setUser(signedIn);
          // Leaving `/auth/callback` is the router's job, not ours. This used
          // to call `history.replaceState` here: the address bar changed, the
          // router did not hear about it — `replaceState` emits no navigation
          // event — and the callback route went on rendering its spinner until
          // the user pressed refresh, at which point the browser re-read the
          // URL and everything worked. Signing in appeared to need a refresh.
          //
          // The route itself now redirects, which also drops the one-time
          // authorization code from the URL.
        } else {
          const existing = await manager.getUser();
          if (cancelled) return;
          setUser(existing && !existing.expired ? existing : null);
        }
      } catch (cause) {
        if (!cancelled) setError(cause as Error);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void bootstrap();

    const onLoaded = (next: User) => setUser(next);
    const onUnloaded = () => setUser(null);
    manager.events.addUserLoaded(onLoaded);
    manager.events.addUserUnloaded(onUnloaded);
    manager.events.addAccessTokenExpired(onUnloaded);

    return () => {
      cancelled = true;
      manager.events.removeUserLoaded(onLoaded);
      manager.events.removeUserUnloaded(onUnloaded);
      manager.events.removeAccessTokenExpired(onUnloaded);
    };
  }, []);

  const signIn = useCallback(() => manager.signinRedirect(), []);
  const signOut = useCallback(async () => {
    await manager.signoutRedirect();
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      isLoading,
      error,
      token: user?.access_token ?? null,
      signIn,
      signOut,
    }),
    [user, isLoading, error, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an <AuthProvider>");
  return context;
}

/** A ref the API client reads, so a token refresh does not rebuild the client. */
export function useTokenRef(): { current: string | null } {
  const { token } = useAuth();
  const ref = useRef<string | null>(token);
  ref.current = token;
  return ref;
}
