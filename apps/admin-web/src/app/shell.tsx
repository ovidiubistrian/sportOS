import { LOCALES } from "@footbola/i18n";
import {
  Avatar,
  Badge,
  Button,
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
  Segmented,
  Tooltip,
  cn,
} from "@footbola/ui";
import {
  ChevronsLeft,
  ChevronsRight,
  ExternalLink,
  Check,
  Languages,
  LogOut,
  Monitor,
  Moon,
  PanelsTopLeft,
  Search,
  Sun,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "./auth";
import { CommandPalette } from "./command-palette";
import { NAVIGATION, activeItem } from "./navigation";
import { useSession } from "./session";
import { useI18n } from "./locale";
import { useTheme } from "./theme";
import { clubSiteUrl } from "./site-url";

/**
 * Application shell.
 *
 * The sidebar is a dark rail in both themes. That is not decoration: it gives
 * the club's colour one place where it reads as identity rather than as
 * chrome, and it keeps the working area — the part with the data in it —
 * uninterrupted.
 *
 * Navigation is generated from resolved permissions: a section the user cannot
 * use does not render. The corresponding routes also 403 server-side — this is
 * for clarity, not for security.
 */

const COLLAPSE_KEY = "footbola.sidebarCollapsed";

function ClubMark({
  club,
  size = "md",
}: {
  club: { short_name: string };
  size?: "md" | "lg";
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-lg bg-brand font-bold text-brand-contrast",
        size === "lg" ? "size-9 text-[0.6875rem]" : "size-7 text-[0.625rem]",
      )}
    >
      {club.short_name.slice(0, 3).toUpperCase()}
    </span>
  );
}

function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  const { t } = useI18n();
  return (
    <Segmented
      ariaLabel={t("nav", "theme")}
      size="sm"
      value={preference}
      onChange={setPreference}
      options={[
        { value: "light", label: <Sun className="size-3.5" />, title: t("nav", "themeLight") },
        { value: "dark", label: <Moon className="size-3.5" />, title: t("nav", "themeDark") },
        { value: "system", label: <Monitor className="size-3.5" />, title: t("nav", "themeSystem") },
      ]}
    />
  );
}

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { me, can, club, path } = useSession();
  const { t } = useI18n();

  return (
    <aside
      className={cn(
        "sticky top-0 flex h-screen shrink-0 flex-col border-r border-nav-border bg-nav-bg",
        "transition-[width] duration-[--duration-base] ease-[--ease-out-soft]",
        collapsed ? "w-[3.75rem]" : "w-60",
      )}
    >
      <div
        className={cn("flex h-14 items-center gap-2.5 px-3", collapsed && "justify-center px-0")}
      >
        <ClubMark club={club} size="lg" />
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-nav-text">
              {club.display_name}
            </p>
            <p className="truncate text-xs text-nav-text-secondary">
              {me.active_tenant?.trading_name ?? me.active_tenant?.legal_name}
            </p>
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-2" aria-label="Main">
        {NAVIGATION.map((group) => {
          const visible = group.items.filter((item) => can(item.permission));
          if (visible.length === 0) return null;

          return (
            <div key={group.labelKey} className="mb-5 last:mb-0">
              {!collapsed && (
                <p className="mb-1.5 px-2.5 text-[0.6875rem] font-medium tracking-wider text-nav-text-secondary uppercase">
                  {t("nav", group.labelKey)}
                </p>
              )}
              <ul className="space-y-0.5">
                {visible.map((item) => {
                  const Icon = item.icon;
                  const link = (
                    <NavLink
                      to={path(item.to)}
                      end={item.end}
                      className={({ isActive }) =>
                        cn(
                          "group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
                          "transition-colors duration-[--duration-fast]",
                          collapsed && "justify-center px-0",
                          isActive
                            ? "bg-nav-surface font-medium text-nav-text"
                            : "text-nav-text-secondary hover:bg-nav-surface/60 hover:text-nav-text",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          {/* The active marker is the club's colour. It is the
                              only brand-coloured element in the rail, which is
                              what makes it read as "you are here". */}
                          <span
                            aria-hidden
                            className={cn(
                              "absolute left-0 h-5 w-0.5 rounded-r-full bg-brand transition-opacity",
                              isActive ? "opacity-100" : "opacity-0",
                            )}
                          />
                          <Icon className="size-4 shrink-0" />
                          {!collapsed && (
                            <span className="truncate">{t("nav", item.labelKey)}</span>
                          )}
                        </>
                      )}
                    </NavLink>
                  );

                  return (
                    <li key={item.to}>
                      {collapsed ? (
                        <Tooltip content={t("nav", item.labelKey)} side="right">
                          <span className="block">{link}</span>
                        </Tooltip>
                      ) : (
                        link
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="border-t border-nav-border p-2">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? t("nav", "expandSidebar") : t("nav", "collapseSidebar")}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
            "text-nav-text-secondary transition-colors hover:bg-nav-surface hover:text-nav-text",
            collapsed && "justify-center px-0",
          )}
        >
          {collapsed ? (
            <ChevronsRight className="size-4" />
          ) : (
            <>
              <ChevronsLeft className="size-4" />
              <span>{t("nav", "collapse")}</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

function Topbar() {
  const { me, club } = useSession();
  const { signOut } = useAuth();
  const { t, locale, setOverride } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const current = activeItem(location.pathname.replace(`/${club.slug}`, "") || "/");

  // The honest test of "is my site live": the same address a supporter would
  // type. Built for the domain this bundle was compiled against — see
  // app/site-url.ts.
  const siteUrl = clubSiteUrl(club.slug);

  const openPalette = () =>
    window.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
    );

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-surface/80 px-5 backdrop-blur-md lg:px-8">
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
        <span className="hidden text-sm text-text-tertiary sm:inline">
          {club.display_name}
        </span>
        <span aria-hidden className="hidden text-text-disabled sm:inline">
          /
        </span>
        <span className="truncate text-sm font-medium text-text">
          {current ? t("nav", current.labelKey) : t("nav", "dashboard")}
        </span>
      </nav>

      <div className="ml-auto flex items-center gap-2">
        {/* Not a search field — a button that opens the palette. A fake input
            that does not accept typing is worse than an honest button. */}
        <button
          type="button"
          onClick={openPalette}
          className={cn(
            "hidden items-center gap-2 rounded-md border border-border bg-bg-subtle px-2.5 py-1.5",
            "text-xs text-text-tertiary transition-colors hover:border-border-strong hover:text-text-secondary",
            "md:flex",
          )}
        >
          <Search className="size-3.5" />
          <span>{t("common", "search")}</span>
          <kbd className="ml-6 font-mono text-[0.625rem]">⌘K</kbd>
        </button>

        <Tooltip content={t("nav", "openClubWebsite")}>
          <Button variant="ghost" size="icon" asChild>
            <a href={siteUrl} target="_blank" rel="noreferrer" aria-label={t("nav", "openClubWebsite")}>
              <ExternalLink />
            </a>
          </Button>
        </Tooltip>

        <ThemeToggle />

        <Menu>
          <MenuTrigger asChild>
            <button
              type="button"
              aria-label={t("nav", "account")}
              className="rounded-full transition-opacity hover:opacity-85"
            >
              <Avatar name={me.email} size="md" />
            </button>
          </MenuTrigger>
          <MenuContent>
            <MenuLabel>{me.email}</MenuLabel>
            {me.workspaces.length > 1 && (
              <>
                <MenuSeparator />
                <MenuLabel>{t("nav", "switchClub")}</MenuLabel>
                {me.workspaces.map((entry) => (
                  <MenuItem
                    key={entry.club.id}
                    disabled={entry.club.id === club.id}
                    onSelect={() => navigate(`/${entry.club.slug}`)}
                  >
                    <PanelsTopLeft />
                    <span className="truncate">{entry.club.display_name}</span>
                    {entry.club.id === club.id && (
                      <Badge tone="brand" className="ml-auto">
                        {t("nav", "current")}
                      </Badge>
                    )}
                  </MenuItem>
                ))}
              </>
            )}
            <MenuSeparator />
            <MenuLabel>{t("settings", "interfaceLanguage")}</MenuLabel>
            {LOCALES.map((option) => (
              <MenuItem
                key={option.code}
                onSelect={() => setOverride(option.code)}
              >
                <Languages />
                {option.endonym}
                {option.code === locale && <Check className="ml-auto" />}
              </MenuItem>
            ))}
            <MenuSeparator />
            <MenuItem destructive onSelect={() => void signOut()}>
              <LogOut />
              {t("common", "signOut")}
            </MenuItem>
          </MenuContent>
        </Menu>
      </div>
    </header>
  );
}

export function Shell() {
  const [collapsed, setCollapsed] = useState(
    () => window.localStorage.getItem(COLLAPSE_KEY) === "true",
  );

  useEffect(() => {
    window.localStorage.setItem(COLLAPSE_KEY, String(collapsed));
  }, [collapsed]);

  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-5 py-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>

      <CommandPalette />
    </div>
  );
}
