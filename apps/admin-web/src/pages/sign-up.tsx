import {
  useSignUp,
  usePlatformLocales,
  useSlugCheck,
  type ApiError,
} from "@footbola/api-client";
import { Button, Card, Field, Input, Spinner, cn } from "@footbola/ui";
import {
  ArrowLeft,
  Check,
  Globe,
  Mail,
  MailCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { PLATFORM_DOMAIN } from "../app/site-url";

/**
 * Sign-up.
 *
 * One screen, not a wizard. Everything asked here is something a club knows
 * without looking anything up — its name, its language, and who is signing up.
 * The configuration that needs thought (template, colours, teams) waits until
 * they are inside and can see what they are changing.
 *
 * The address is checked as they type, because the club's name is usually the
 * address they want and finding out it is taken *after* filling in a password
 * is the worst moment to be told.
 */


const COUNTRIES = [
  { code: "RO", name: "România" },
  { code: "MD", name: "Moldova" },
  { code: "GB", name: "United Kingdom" },
  { code: "DE", name: "Deutschland" },
  { code: "FR", name: "France" },
  { code: "ES", name: "España" },
  { code: "IT", name: "Italia" },
  { code: "NL", name: "Nederland" },
  { code: "PT", name: "Portugal" },
  { code: "PL", name: "Polska" },
];

const MIN_PASSWORD = 12;

function useDebounced<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function CheckMail({ email }: { email: string }) {
  return (
    <div className="w-full max-w-md text-center">
      <span
        aria-hidden
        className="mx-auto mb-5 grid size-12 place-items-center rounded-xl bg-success-bg text-success"
      >
        <MailCheck className="size-6" />
      </span>
      <h1 className="text-xl font-semibold text-text">Check your email</h1>
      <p className="mt-2 text-sm text-text-secondary">
        We sent a link to <strong className="text-text">{email}</strong>. Open it to
        confirm the address, and your club is ready.
      </p>
      <Card className="mt-6 p-4 text-left">
        <p className="text-sm text-text-secondary">
          You cannot sign in until the address is confirmed. That is deliberate — it
          stops anyone claiming a club's name with an email they do not control.
        </p>
      </Card>
      <Button variant="ghost" className="mt-6" asChild>
        <a href="/">
          <ArrowLeft />
          Back to the site
        </a>
      </Button>
    </div>
  );
}

export function SignUpPage() {
  const locales = usePlatformLocales();
  const signUp = useSignUp();

  const [clubName, setClubName] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [slug, setSlug] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [country, setCountry] = useState("RO");
  const [locale, setLocale] = useState("ro");

  // The address follows the club's name until someone edits it, and then stops
  // fighting them.
  useEffect(() => {
    if (slugEdited) return;
    const derived = clubName
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48);
    setSlug(derived);
  }, [clubName, slugEdited]);

  const debouncedSlug = useDebounced(slug);
  const slugCheck = useSlugCheck(debouncedSlug);
  const checking = slugCheck.isFetching;
  const available = slugCheck.data?.available ?? null;
  const suggestion = slugCheck.data?.suggestion ?? null;

  const fieldErrors = useMemo(
    () => (signUp.error as ApiError | null)?.fieldErrors ?? {},
    [signUp.error],
  );

  const ready =
    clubName.trim().length >= 2 &&
    slug.length >= 3 &&
    available === true &&
    firstName.trim() &&
    lastName.trim() &&
    email.includes("@") &&
    password.length >= MIN_PASSWORD;

  if (signUp.isSuccess) {
    return (
      <div className="grid min-h-screen place-items-center bg-bg p-6">
        <CheckMail email={signUp.data.email} />
      </div>
    );
  }

  return (
    <div className="grid min-h-screen place-items-center bg-bg p-6">
      <div className="w-full max-w-lg">
        <div className="mb-7 text-center">
          <span
            aria-hidden
            className="mx-auto mb-4 grid size-11 place-items-center rounded-xl bg-brand text-xs font-bold text-brand-contrast shadow-md"
          >
            FOS
          </span>
          <h1 className="text-2xl font-semibold text-text">Set up your club</h1>
          <p className="mt-1.5 text-sm text-text-secondary">
            Two minutes. Your website is live at the end of it.
          </p>
        </div>

        <Card className="space-y-5 p-6">
          {signUp.isError && !Object.keys(fieldErrors).length && (
            <p
              role="alert"
              className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger"
            >
              {signUp.error.message}
            </p>
          )}

          <Field
            label="Club name"
            htmlFor="club-name"
            required
            error={fieldErrors.club_name}
          >
            {(props) => (
              <Input
                {...props}
                value={clubName}
                autoFocus
                placeholder="Sportul Studențesc"
                onChange={(event) => setClubName(event.target.value)}
              />
            )}
          </Field>

          <Field
            label="Web address"
            htmlFor="club-slug"
            required
            error={fieldErrors.slug}
            help="This is where your club lives. It cannot be changed later."
          >
            {(props) => (
              <>
                <div className="flex items-center gap-1.5">
                  <Input
                    {...props}
                    value={slug}
                    className="font-mono"
                    onChange={(event) => {
                      setSlugEdited(true);
                      setSlug(
                        event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""),
                      );
                    }}
                    trailing={
                      checking ? (
                        <Spinner />
                      ) : available === true ? (
                        <Check className="text-success" />
                      ) : available === false ? (
                        <X className="text-danger" />
                      ) : null
                    }
                  />
                  <span className="shrink-0 text-sm text-text-tertiary">
                    .{PLATFORM_DOMAIN}
                  </span>
                </div>
                {available === false && suggestion && (
                  <button
                    type="button"
                    className="mt-1.5 text-xs text-brand-text underline-offset-2 hover:underline"
                    onClick={() => {
                      setSlugEdited(true);
                      setSlug(suggestion);
                    }}
                  >
                    Taken. Try {suggestion} instead?
                  </button>
                )}
              </>
            )}
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Country" htmlFor="country" required>
              {(props) => (
                <select
                  {...props}
                  value={country}
                  onChange={(event) => setCountry(event.target.value)}
                  className="h-8 w-full rounded-md border border-border bg-surface px-2.5 text-sm text-text shadow-xs"
                >
                  {COUNTRIES.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>

            <Field
              label="Language"
              htmlFor="locale"
              required
              help="What your club works in. You can publish in more later."
            >
              {(props) => (
                <select
                  {...props}
                  value={locale}
                  onChange={(event) => setLocale(event.target.value)}
                  className="h-8 w-full rounded-md border border-border bg-surface px-2.5 text-sm text-text shadow-xs"
                >
                  {(locales.data ?? []).map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.endonym}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </div>

          <div className="border-t border-border pt-5">
            <p className="mb-4 flex items-center gap-1.5 text-xs font-medium tracking-wide text-text-tertiary uppercase">
              <Globe className="size-3.5" />
              Your account
            </p>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="First name" htmlFor="first-name" required>
                {(props) => (
                  <Input
                    {...props}
                    value={firstName}
                    onChange={(event) => setFirstName(event.target.value)}
                  />
                )}
              </Field>
              <Field label="Last name" htmlFor="last-name" required>
                {(props) => (
                  <Input
                    {...props}
                    value={lastName}
                    onChange={(event) => setLastName(event.target.value)}
                  />
                )}
              </Field>
            </div>

            <Field
              className="mt-4"
              label="Email"
              htmlFor="email"
              required
              error={fieldErrors.email}
              help="We send a confirmation link here."
            >
              {(props) => (
                <Input
                  {...props}
                  type="email"
                  value={email}
                  leading={<Mail />}
                  autoComplete="email"
                  onChange={(event) => setEmail(event.target.value)}
                />
              )}
            </Field>

            <Field
              className="mt-4"
              label="Password"
              htmlFor="password"
              required
              error={fieldErrors.password}
              help={`At least ${MIN_PASSWORD} characters. A short sentence works well and is harder to guess than a word with symbols in it.`}
            >
              {(props) => (
                <>
                  <Input
                    {...props}
                    type="password"
                    value={password}
                    autoComplete="new-password"
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  <div
                    aria-hidden
                    className="mt-1.5 h-1 overflow-hidden rounded-full bg-bg-muted"
                  >
                    <div
                      className={cn(
                        "h-full rounded-full transition-[width,background-color]",
                        password.length >= MIN_PASSWORD ? "bg-success" : "bg-warning",
                      )}
                      style={{
                        width: `${Math.min(100, (password.length / MIN_PASSWORD) * 100)}%`,
                      }}
                    />
                  </div>
                </>
              )}
            </Field>
          </div>

          <Button
            variant="primary"
            size="lg"
            className="w-full"
            disabled={!ready}
            loading={signUp.isPending}
            onClick={() =>
              signUp.mutate({
                email: email.trim().toLowerCase(),
                password,
                first_name: firstName.trim(),
                last_name: lastName.trim(),
                club_name: clubName.trim(),
                slug,
                country_code: country,
                locale,
              })
            }
          >
            Create my club
          </Button>
        </Card>

        <p className="mt-5 text-center text-sm text-text-secondary">
          Already have a club?{" "}
          <Link to="/signin" className="text-brand-text hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
