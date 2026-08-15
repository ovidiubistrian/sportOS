import { useMe } from "@footbola/api-client";
import { createTranslator, normaliseLocale } from "@footbola/i18n";
import { Badge, Button, Card, Skeleton, cn } from "@footbola/ui";
import { ArrowRight, Building2, LogOut } from "lucide-react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../app/auth";
import { getStoredClubSlug } from "../app/session";

/**
 * Which club are you working in?
 *
 * Everyone signs in at the same address. This is the one screen between that
 * and the club itself, and for the overwhelming majority — one person, one
 * club — it never appears: a single workspace redirects straight through, and
 * a returning user goes back to the club they were last in.
 *
 * It also handles the honest failure: a bookmarked slug for a club the account
 * can no longer reach. Saying so plainly beats a blank screen or a 403 the user
 * cannot act on.
 */
export function WorkspacePicker({ unknownSlug }: { unknownSlug?: string }) {
  const { data, isLoading, error } = useMe();
  // No tenant has been chosen yet, so there is no tenant language to follow.
  // The browser's is the only signal available here — and it is the right one:
  // it is what this person already told their device.
  const { t } = createTranslator(normaliseLocale(navigator.language));
  const { signOut } = useAuth();
  const navigate = useNavigate();

  const workspaces = data?.workspaces ?? [];
  const remembered = getStoredClubSlug();

  useEffect(() => {
    if (!data || unknownSlug) return;

    // A platform operator is not a member of any club, so there is nothing to
    // pick — they belong in the super-admin console.
    if (data.is_platform_user && workspaces.length === 0) {
      navigate("/platform", { replace: true });
      return;
    }

    // One club, or the one they were last in: go straight there. The picker is
    // for the minority who genuinely have a choice to make.
    const target =
      workspaces.find((workspace) => workspace.club.slug === remembered) ??
      (workspaces.length === 1 ? workspaces[0] : undefined);
    if (target) navigate(`/${target.club.slug}`, { replace: true });
  }, [data, workspaces, remembered, unknownSlug, navigate]);

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-bg p-6">
        <div className="w-full max-w-md space-y-3">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </div>
    );
  }

  const empty = workspaces.length === 0;

  return (
    <div className="grid min-h-screen place-items-center bg-bg p-6">
      <div className="w-full max-w-md">
        <div className="mb-7 text-center">
          <span
            aria-hidden
            className="mx-auto mb-4 grid size-11 place-items-center rounded-xl bg-brand text-xs font-bold text-brand-contrast shadow-md"
          >
            FOS
          </span>
          <h1 className="text-xl font-semibold text-text">
            {t("workspace", empty ? "noAccessTitle" : "chooseTitle")}
          </h1>
          <p className="mt-1.5 text-sm text-text-secondary">
            {unknownSlug
              ? t("workspace", "unknownSlug", { slug: unknownSlug })
              : empty
                ? (error?.message ?? t("workspace", "noAccessBody"))
                : t("workspace", "chooseSubtitle", { email: data?.email ?? "" })}
          </p>
        </div>

        <div className="space-y-2">
          {workspaces.map((workspace) => (
            <Card
              key={workspace.club.id}
              interactive
              className="group cursor-pointer p-3"
              onClick={() => navigate(`/${workspace.club.slug}`)}
            >
              <div className="flex items-center gap-3">
                <span
                  aria-hidden
                  className={cn(
                    "grid size-10 shrink-0 place-items-center rounded-lg text-[0.6875rem] font-bold text-white shadow-sm",
                  )}
                  style={{ background: workspace.club.color_primary }}
                >
                  {workspace.club.short_name.slice(0, 3).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-text">
                    {workspace.club.display_name}
                  </p>
                  <p className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-text-tertiary">
                    <Building2 className="size-3" />
                    {workspace.tenant_name}
                  </p>
                </div>
                {workspace.club.slug === remembered && (
                  <Badge tone="outline">{t("workspace", "lastUsed")}</Badge>
                )}
                <ArrowRight className="size-4 shrink-0 text-text-tertiary transition-transform group-hover:translate-x-0.5" />
              </div>
            </Card>
          ))}
        </div>

        <Button variant="ghost" className="mt-6 w-full" onClick={() => void signOut()}>
          <LogOut />
          {t("common", "signOut")}
        </Button>
      </div>
    </div>
  );
}
