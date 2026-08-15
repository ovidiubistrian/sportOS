import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/* --- Button ---------------------------------------------------------------
 *
 * Five variants, and the ranking between them is the point: exactly one primary
 * action per view. A screen with three primary buttons has told the user
 * nothing about what to do next.
 */

const button = cva(
  [
    "inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium",
    "rounded-md border border-transparent select-none",
    "transition-[background-color,border-color,color,box-shadow,transform]",
    "duration-[--duration-fast] ease-[--ease-out-soft]",
    "active:scale-[0.985]",
    "disabled:pointer-events-none disabled:opacity-50",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
  ].join(" "),
  {
    variants: {
      variant: {
        primary:
          "bg-brand text-brand-contrast shadow-xs hover:bg-brand-hover hover:shadow-sm",
        secondary:
          "border-border bg-surface text-text shadow-xs hover:border-border-strong hover:bg-surface-hover",
        ghost: "text-text-secondary hover:bg-surface-hover hover:text-text",
        danger: "bg-danger text-white shadow-xs hover:brightness-110",
        // Reads as a link, behaves as a button. For inline actions inside prose
        // and table cells, where a bordered control would be visual noise.
        link: "text-brand-text underline-offset-4 hover:underline",
      },
      size: {
        xs: "h-6 px-2 text-xs [&_svg]:size-3",
        sm: "h-7 px-2.5 text-xs [&_svg]:size-3.5",
        md: "h-8 px-3 text-sm [&_svg]:size-4",
        lg: "h-10 px-4 text-base [&_svg]:size-4",
        // Square, for a lone icon. Sized so it lines up with the text control
        // of the same step.
        icon: "size-8 [&_svg]:size-4",
        "icon-sm": "size-7 [&_svg]:size-3.5",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
  /** Shows a spinner and blocks input. The label stays, so width does not jump. */
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, loading, children, disabled, ...props },
    ref,
  ) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={cn(button({ variant, size }), className)}
        {...props}
      >
        {loading ? (
          <>
            <Spinner />
            {children}
          </>
        ) : (
          children
        )}
      </Component>
    );
  },
);
Button.displayName = "Button";

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("size-3.5 animate-spin", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* --- Input & Textarea ----------------------------------------------------- */

const fieldBase = [
  "w-full rounded-md border border-border bg-surface text-sm text-text",
  "shadow-xs transition-[border-color,box-shadow] duration-[--duration-fast]",
  "placeholder:text-text-tertiary",
  "hover:border-border-strong",
  "focus-visible:border-brand focus-visible:outline-2 focus-visible:outline-offset-0",
  "focus-visible:outline-brand",
  "disabled:cursor-not-allowed disabled:bg-bg-muted disabled:text-text-disabled",
  "aria-[invalid=true]:border-danger aria-[invalid=true]:outline-danger",
].join(" ");

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Rendered inside the control, left of the text. Usually a 16px icon. */
  leading?: ReactNode;
  trailing?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, leading, trailing, ...props }, ref) => {
    if (!leading && !trailing) {
      return (
        <input ref={ref} className={cn(fieldBase, "h-8 px-2.5", className)} {...props} />
      );
    }
    return (
      <div className="relative flex items-center">
        {leading && (
          <span className="pointer-events-none absolute left-2.5 flex text-text-tertiary [&_svg]:size-4">
            {leading}
          </span>
        )}
        <input
          ref={ref}
          className={cn(fieldBase, "h-8 px-2.5", leading && "pl-8", trailing && "pr-8", className)}
          {...props}
        />
        {trailing && (
          <span className="absolute right-2.5 flex text-text-tertiary [&_svg]:size-4">
            {trailing}
          </span>
        )}
      </div>
    );
  },
);
Input.displayName = "Input";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, rows = 3, ...props }, ref) => (
  <textarea
    ref={ref}
    rows={rows}
    className={cn(fieldBase, "resize-y px-2.5 py-1.5 leading-relaxed", className)}
    {...props}
  />
));
Textarea.displayName = "Textarea";

/* --- Field ---------------------------------------------------------------
 *
 * Label, help text and error in one place, wired together. Doing this by hand
 * per form is how `aria-describedby` quietly stops matching anything.
 */

let fieldSeq = 0;

export function Field({
  label,
  help,
  error,
  required,
  children,
  className,
  htmlFor,
}: {
  label: string;
  help?: string;
  error?: string | null;
  required?: boolean;
  children: (props: {
    id: string;
    "aria-describedby": string | undefined;
    "aria-invalid": boolean | undefined;
  }) => ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  const id = htmlFor ?? `field-${(fieldSeq += 1)}`;
  const helpId = help ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;

  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="flex items-center gap-1 text-xs font-medium text-text">
        {label}
        {required && (
          <span className="text-danger" aria-hidden>
            *
          </span>
        )}
      </label>
      {children({
        id,
        "aria-describedby": [errorId, helpId].filter(Boolean).join(" ") || undefined,
        "aria-invalid": error ? true : undefined,
      })}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : (
        help && (
          <p id={helpId} className="text-xs leading-relaxed text-text-tertiary">
            {help}
          </p>
        )
      )}
    </div>
  );
}

/* --- Badge ---------------------------------------------------------------- */

const badge = cva(
  "inline-flex items-center gap-1 rounded-full font-medium leading-none whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-bg-muted text-text-secondary",
        success: "bg-success-bg text-success",
        warning: "bg-warning-bg text-warning",
        danger: "bg-danger-bg text-danger",
        info: "bg-info-bg text-info",
        brand: "bg-brand-subtle text-brand-text",
        outline: "border border-border bg-transparent text-text-secondary",
      },
      size: {
        sm: "px-1.5 py-0.5 text-[0.6875rem]",
        md: "px-2 py-1 text-xs",
      },
    },
    defaultVariants: { tone: "neutral", size: "sm" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badge> {
  /** A 6px filled circle before the label, for status. */
  dot?: boolean;
}

export function Badge({ className, tone, size, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badge({ tone, size }), className)} {...props}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current opacity-80" />}
      {children}
    </span>
  );
}

/* --- Skeleton ------------------------------------------------------------- */

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  // A sweep rather than a pulse: a pulse reads as "broken", a sweep reads as
  // "arriving".
  return (
    <div
      aria-hidden
      className={cn("rounded-md bg-bg-muted", className)}
      style={{
        backgroundImage:
          "linear-gradient(90deg, transparent 0%, rgb(255 255 255 / 0.55) 50%, transparent 100%)",
        backgroundSize: "200% 100%",
        animation: "fos-shimmer 1.4s linear infinite",
      }}
      {...props}
    />
  );
}

/* --- Surfaces ------------------------------------------------------------- */

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** `raised` adds a shadow. Use it for things that float, not for layout. */
  elevation?: "flat" | "raised";
  interactive?: boolean;
}

export function Card({
  className,
  elevation = "flat",
  interactive,
  ...props
}: CardProps) {
  // A card gets a border, not a shadow: a shadow means "floating above the
  // page", which a card in a layout does not do.
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface",
        elevation === "raised" && "shadow-md",
        interactive &&
          "transition-[border-color,box-shadow,transform] duration-[--duration-fast] hover:-translate-y-px hover:border-border-strong hover:shadow-md",
        className,
      )}
      {...props}
    />
  );
}

export function Separator({
  className,
  orientation = "horizontal",
}: {
  className?: string;
  orientation?: "horizontal" | "vertical";
}) {
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={cn(
        "bg-border",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
    />
  );
}

/* --- Avatar ---------------------------------------------------------------
 *
 * Initials on a colour derived from the name, so a squad list is scannable
 * without a single uploaded photo — which is the normal state of a club that
 * has just signed up.
 */

const AVATAR_TONES = [
  "bg-[#e8effb] text-[#1f4b99]",
  "bg-[#e6f5ee] text-[#04724d]",
  "bg-[#fdefe2] text-[#8a5300]",
  "bg-[#f3ebfb] text-[#5b32a3]",
  "bg-[#fdeaee] text-[#a51d38]",
  "bg-[#e4f4f6] text-[#0f6172]",
];

function toneFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  return AVATAR_TONES[Math.abs(hash) % AVATAR_TONES.length] as string;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

export function Avatar({
  name,
  src,
  size = "md",
  className,
}: {
  name: string;
  src?: string | null;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  className?: string;
}) {
  const sizes = {
    xs: "size-5 text-[0.5625rem]",
    sm: "size-6 text-[0.625rem]",
    md: "size-8 text-xs",
    lg: "size-10 text-sm",
    xl: "size-16 text-lg",
  } as const;

  if (src) {
    return (
      <img
        src={src}
        alt=""
        className={cn(
          "shrink-0 rounded-full border border-border object-cover",
          sizes[size],
          className,
        )}
      />
    );
  }
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-semibold",
        sizes[size],
        toneFor(name),
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}

/* --- Progress ------------------------------------------------------------- */

export function Progress({
  value,
  max = 100,
  tone = "brand",
  className,
  label,
}: {
  value: number;
  max?: number;
  tone?: "brand" | "success" | "warning" | "danger";
  className?: string;
  label?: string;
}) {
  const percent = max === 0 ? 0 : Math.min(100, Math.max(0, (value / max) * 100));
  const fills = {
    brand: "bg-brand",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
  } as const;

  return (
    <div
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-bg-muted", className)}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-[--duration-slow] ease-[--ease-out-soft]",
          fills[tone],
        )}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

/* --- Segmented control ----------------------------------------------------
 *
 * For two to four mutually exclusive options that are all worth showing. Past
 * four, it becomes a Select — a row of eight segments is a menu wearing a
 * disguise.
 */

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = "md",
  className,
  ariaLabel,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: ReactNode; title?: string }[];
  size?: "sm" | "md";
  className?: string;
  ariaLabel: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md border border-border bg-bg-subtle p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-[5px] font-medium transition-colors duration-[--duration-fast]",
              size === "sm" ? "h-6 px-2 text-xs" : "h-7 px-2.5 text-sm",
              selected
                ? "bg-surface text-text shadow-xs"
                : "text-text-secondary hover:text-text",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/* --- Switch --------------------------------------------------------------- */

export function Switch({
  checked,
  onChange,
  disabled,
  label,
  id,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label: string;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full",
        "transition-colors duration-[--duration-fast]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-brand" : "bg-border-strong",
      )}
    >
      <span
        className={cn(
          "block size-4 rounded-full bg-white shadow-sm",
          "transition-transform duration-[--duration-fast] ease-[--ease-out-soft]",
          checked ? "translate-x-[1.125rem]" : "translate-x-0.5",
        )}
      />
    </button>
  );
}
