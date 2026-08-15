import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import * as SelectPrimitive from "@radix-ui/react-select";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Check, ChevronDown, X } from "lucide-react";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ComponentPropsWithoutRef,
  type ElementRef,
  type ReactNode,
} from "react";

import { cn } from "./primitives";

/* Everything here is built on Radix: focus trapping, escape handling, typeahead
 * and ARIA wiring are the parts of a menu that are hard to get right and easy
 * to get subtly wrong, and they are not where this product's value lies. */

const surfaceIn =
  "data-[state=open]:animate-scale-in data-[state=closed]:opacity-0 " +
  "rounded-lg border border-border bg-surface-raised shadow-lg";

/* --- Tooltip -------------------------------------------------------------- */

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({
  content,
  children,
  side = "top",
  shortcut,
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  shortcut?: string;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 flex items-center gap-2 rounded-md bg-nav-bg px-2 py-1.5",
            "text-xs font-medium text-nav-text shadow-lg",
            "data-[state=delayed-open]:animate-scale-in",
          )}
        >
          {content}
          {shortcut && (
            <kbd className="rounded border border-white/20 px-1 font-mono text-[0.625rem] text-white/70">
              {shortcut}
            </kbd>
          )}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

/* --- Dropdown menu -------------------------------------------------------- */

export const Menu = DropdownMenuPrimitive.Root;
export const MenuTrigger = DropdownMenuPrimitive.Trigger;

export const MenuContent = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 6, align = "end", ...props }, ref) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(surfaceIn, "z-50 min-w-[11rem] p-1", className)}
      {...props}
    />
  </DropdownMenuPrimitive.Portal>
));
MenuContent.displayName = "MenuContent";

const itemBase = [
  "relative flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm",
  "text-text outline-none select-none",
  "data-[highlighted]:bg-surface-hover data-[highlighted]:text-text",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
  "[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-text-tertiary",
].join(" ");

export const MenuItem = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Item>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & { destructive?: boolean }
>(({ className, destructive, ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      itemBase,
      destructive && "text-danger data-[highlighted]:bg-danger-bg [&_svg]:text-danger",
      className,
    )}
    {...props}
  />
));
MenuItem.displayName = "MenuItem";

export function MenuLabel({ children }: { children: ReactNode }) {
  return (
    <DropdownMenuPrimitive.Label className="px-2 py-1.5 text-xs font-medium text-text-tertiary">
      {children}
    </DropdownMenuPrimitive.Label>
  );
}

export function MenuSeparator() {
  return <DropdownMenuPrimitive.Separator className="my-1 h-px bg-border" />;
}

export function MenuShortcut({ children }: { children: ReactNode }) {
  return (
    <span className="ml-auto font-mono text-xs tracking-widest text-text-tertiary">
      {children}
    </span>
  );
}

/* --- Select --------------------------------------------------------------- */

export interface SelectOption<T extends string> {
  value: T;
  label: string;
  description?: string;
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  placeholder = "Select…",
  ariaLabel,
  id,
  size = "md",
  className,
  disabled,
}: {
  value: T | "";
  onChange: (value: T) => void;
  options: SelectOption<T>[];
  placeholder?: string;
  ariaLabel?: string;
  id?: string;
  size?: "sm" | "md";
  className?: string;
  disabled?: boolean;
}) {
  return (
    <SelectPrimitive.Root
      value={value || undefined}
      onValueChange={(next) => onChange(next as T)}
      disabled={disabled}
    >
      <SelectPrimitive.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cn(
          "inline-flex w-full items-center justify-between gap-2 rounded-md border border-border",
          "bg-surface text-sm text-text shadow-xs",
          "transition-[border-color] duration-[--duration-fast]",
          "hover:border-border-strong",
          "focus-visible:border-brand focus-visible:outline-2 focus-visible:outline-brand",
          "disabled:cursor-not-allowed disabled:bg-bg-muted disabled:text-text-disabled",
          "data-[placeholder]:text-text-tertiary",
          size === "sm" ? "h-7 px-2 text-xs" : "h-8 px-2.5",
          className,
        )}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon>
          <ChevronDown className="size-3.5 text-text-tertiary" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>

      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          className={cn(surfaceIn, "z-50 max-h-72 min-w-[var(--radix-select-trigger-width)]")}
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                className={cn(itemBase, "pr-8")}
              >
                <div className="min-w-0">
                  <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                  {option.description && (
                    <p className="mt-0.5 text-xs text-text-tertiary">{option.description}</p>
                  )}
                </div>
                <SelectPrimitive.ItemIndicator className="absolute right-2">
                  <Check className="size-4 text-brand-text" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

/* --- Dialog --------------------------------------------------------------- */

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  const widths = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-3xl" } as const;
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-overlay backdrop-blur-[2px] data-[state=open]:animate-fade-in" />
        <DialogPrimitive.Content
          className={cn(
            "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2",
            "rounded-xl border border-border bg-surface-raised shadow-xl",
            "data-[state=open]:animate-scale-in",
            widths[size],
          )}
        >
          <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-base font-semibold text-text">
                {title}
              </DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description className="mt-1 text-sm text-text-secondary">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close
              aria-label="Close"
              className="-mt-1 -mr-1 grid size-7 shrink-0 place-items-center rounded-md text-text-tertiary transition-colors hover:bg-surface-hover hover:text-text"
            >
              <X className="size-4" />
            </DialogPrimitive.Close>
          </header>

          {children && <div className="px-5 py-4">{children}</div>}

          {footer && (
            <footer className="flex items-center justify-end gap-2 border-t border-border bg-bg-subtle px-5 py-3">
              {footer}
            </footer>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export const DialogClose = DialogPrimitive.Close;

/* --- Toast ----------------------------------------------------------------
 *
 * Deliberately minimal: a confirmation that something saved, and an error that
 * something did not. Anything a user must act on belongs in the page, not in a
 * message that disappears after four seconds.
 */

export interface ToastMessage {
  id: number;
  tone: "success" | "danger" | "info";
  title: string;
  description?: string;
}

interface ToastApi {
  show: (toast: Omit<ToastMessage, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast must be used inside a <ToastProvider>");
  return api;
}

let toastSeq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const show = useCallback((toast: Omit<ToastMessage, "id">) => {
    const id = (toastSeq += 1);
    setToasts((current) => [...current, { ...toast, id }]);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (title, description) => show({ tone: "success", title, description }),
      error: (title, description) => show({ tone: "danger", title, description }),
    }),
    [show],
  );

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-80 flex-col gap-2"
      >
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: ToastMessage;
  onDismiss: (id: number) => void;
}) {
  useEffect(() => {
    // Errors stay longer: they usually carry something worth reading.
    const timeout = window.setTimeout(
      () => onDismiss(toast.id),
      toast.tone === "danger" ? 7000 : 4000,
    );
    return () => window.clearTimeout(timeout);
  }, [toast, onDismiss]);

  const accents = {
    success: "bg-success",
    danger: "bg-danger",
    info: "bg-info",
  } as const;

  return (
    <div
      role={toast.tone === "danger" ? "alert" : "status"}
      className="animate-slide-up pointer-events-auto flex gap-3 overflow-hidden rounded-lg border border-border bg-surface-raised shadow-lg"
    >
      <span aria-hidden className={cn("w-1 shrink-0", accents[toast.tone])} />
      <div className="min-w-0 flex-1 py-2.5">
        <p className="text-sm font-medium text-text">{toast.title}</p>
        {toast.description && (
          <p className="mt-0.5 text-xs text-text-secondary">{toast.description}</p>
        )}
      </div>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => onDismiss(toast.id)}
        className="grid size-7 shrink-0 place-items-center self-start text-text-tertiary transition-colors hover:text-text"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
