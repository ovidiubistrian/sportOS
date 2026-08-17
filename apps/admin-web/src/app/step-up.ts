import { ApiError } from "@footbola/api-client";
import { useCallback } from "react";

import { useAuth } from "./auth";

/**
 * Running something that may demand a second factor.
 *
 * A handful of actions — the card gateway's credentials, clinical records,
 * impersonating a tenant's user — answer 401 `STEP_UP_REQUIRED` even to
 * somebody who holds the permission. A permission check does not address the
 * threat those actions actually face, which is a session somebody else is
 * holding; only asking again, for something that is not a password, does.
 *
 * The shape is deliberately "try, and try once more". Asking for a code before
 * the action would demand one from people who were only looking, and would
 * demand it again fifteen minutes later for no reason they could see. Asking
 * only when the server says so means the prompt appears exactly when it is
 * warranted, and never otherwise.
 *
 * The retry is what makes the popup worth it: the page never went away, so the
 * form is still filled in and the second attempt carries the same values as the
 * first. The caller writes no code for any of this beyond wrapping the call.
 */
export function useStepUp() {
  const { stepUp } = useAuth();

  return useCallback(
    async <T>(action: () => Promise<T>): Promise<T> => {
      try {
        return await action();
      } catch (error) {
        if (!(error instanceof ApiError) || !error.needsStepUp) throw error;
        // Throws if the person closes the popup or fails the code. That is a
        // refusal, and it belongs to the caller's error handling like any
        // other — being unable to prove yourself is not a bug.
        await stepUp();
        return await action();
      }
    },
    [stepUp],
  );
}
