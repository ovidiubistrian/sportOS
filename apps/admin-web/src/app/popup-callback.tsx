import { UserManager } from "oidc-client-ts";
import { useEffect } from "react";

/**
 * Where the step-up popup lands.
 *
 * It has one job: hand the result back to the window that opened it and close.
 * Nothing is rendered for longer than an instant, and nothing here belongs to
 * the application — the page underneath never went away, which is the whole
 * reason a popup is used for this rather than a redirect.
 */
export function PopupCallbackPage() {
  useEffect(() => {
    void new UserManager({
      authority: import.meta.env.VITE_OIDC_ISSUER as string,
      client_id: import.meta.env.VITE_OIDC_CLIENT_ID as string,
      redirect_uri: `${window.location.origin}/auth/popup`,
    })
      .signinPopupCallback()
      .catch(() => {
        // The opener is watching the promise and will report the failure with
        // the context to explain it. Closing regardless avoids leaving an
        // orphaned window on screen.
        window.close();
      });
  }, []);

  return null;
}
