import { cn } from "@footbola/ui";
import { CornerDownLeft, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ALL_NAV_ITEMS, type NavItem } from "./navigation";
import { useI18n } from "./locale";
import { useSession } from "./session";

/**
 * ⌘K.
 *
 * The fastest route to anywhere, and the one affordance that makes an admin
 * tool feel like it was built for people who use it every day rather than
 * once. It only ever navigates — no destructive command is reachable from a
 * text box you can type into by accident.
 */

interface Command extends NavItem {
  label: string;
  description: string;
}

function score(query: string, command: Command): number {
  // Keywords are matched in every language we ship, so someone typing
  // "jucatori" finds Players even while the interface is in English.
  const haystack = [command.label, command.description, ...(command.keywords ?? [])]
    .join(" ")
    .toLowerCase();
  const needle = query.toLowerCase().trim();
  if (!needle) return 1;
  if (command.label.toLowerCase().startsWith(needle)) return 3;
  if (haystack.includes(needle)) return 2;
  return 0;
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const navigate = useNavigate();
  const { can, path } = useSession();
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // The input mounts with the dialog, so focus has to wait a frame.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const commands = useMemo<Command[]>(
    () =>
      ALL_NAV_ITEMS.filter((item) => can(item.permission)).map((item) => ({
        ...item,
        label: t("nav", item.labelKey),
        description: item.descriptionKey ? t("nav", item.descriptionKey) : "",
      })),
    [can, t],
  );

  const results = useMemo(
    () =>
      commands
        .map((command) => ({ command, rank: score(query, command) }))
        .filter((entry) => entry.rank > 0)
        .sort((a, b) => b.rank - a.rank)
        .map((entry) => entry.command),
    [commands, query],
  );

  if (!open) return null;

  const run = (command: Command) => {
    navigate(path(command.to));
    setOpen(false);
  };

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center p-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <button
        type="button"
        aria-label={t("common", "close")}
        tabIndex={-1}
        className="fixed inset-0 animate-fade-in cursor-default bg-overlay backdrop-blur-[2px]"
        onClick={() => setOpen(false)}
      />

      <div className="animate-scale-in relative w-full max-w-lg overflow-hidden rounded-xl border border-border bg-surface-raised shadow-xl">
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search className="size-4 shrink-0 text-text-tertiary" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setCursor((c) => Math.min(c + 1, results.length - 1));
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              }
              if (event.key === "Enter" && results[cursor]) {
                event.preventDefault();
                run(results[cursor]);
              }
            }}
            placeholder={t("nav", "commandPlaceholder")}
            aria-label={t("common", "search")}
            className="h-12 w-full bg-transparent text-sm text-text outline-none placeholder:text-text-tertiary"
          />
          <kbd className="rounded border border-border px-1.5 py-0.5 font-mono text-[0.625rem] text-text-tertiary">
            esc
          </kbd>
        </div>

        <div className="max-h-80 overflow-y-auto p-1.5">
          {results.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-text-tertiary">
              {t("nav", "commandEmpty", { query })}
            </p>
          ) : (
            results.map((command, index) => {
              const Icon = command.icon;
              return (
                <button
                  key={command.to}
                  type="button"
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => run(command)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors",
                    index === cursor ? "bg-surface-hover" : "hover:bg-surface-hover",
                  )}
                >
                  <span className="grid size-7 shrink-0 place-items-center rounded-md bg-bg-muted text-text-secondary">
                    <Icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-text">{command.label}</span>
                    {command.description && (
                      <span className="block truncate text-xs text-text-tertiary">
                        {command.description}
                      </span>
                    )}
                  </span>
                  {index === cursor && (
                    <CornerDownLeft className="size-3.5 shrink-0 text-text-tertiary" />
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
