"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Dialog as AstryxDialog } from "@astryxdesign/core/Dialog";
import { useMergedRefs } from "@astryxdesign/core/hooks";
import { useControllableState } from "@radix-ui/react-use-controllable-state";
import { XIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Portal, Slot } from "radix-ui";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { PortalContainerContext } from "@/components/ui/portal-container";
import { cn } from "@/lib/utils";

/*
 * shadcn's Dialog API, rendered by Astryx Dialog: a native modal <dialog> in
 * the top layer. The browser makes everything outside it inert, Escape goes
 * through Astryx's layer stack (one press closes one layer), the title is
 * focused on open and names the dialog, and focus returns to the trigger on
 * close. alert-dialog.tsx builds on the same parts, so the whole app has one
 * dialog implementation.
 *
 * The call sites' classes (`sm:max-w-2xl`, `max-h-[90vh] overflow-y-auto`,
 * `p-0`, `flex flex-col`, …) style the <dialog> itself, as they styled
 * shadcn's content box. Astryx wraps the children in one layout div; it is
 * flattened (`display: contents`) so those classes lay the children out.
 */

type DialogContextValue = {
  open: boolean;
  setOpen: (open: boolean) => void;
  contentId: string;
  titleId: string;
  descriptionId: string;
  hasDescription: boolean;
  registerDescription: () => () => void;
  triggerRef: React.RefObject<HTMLElement | null>;
};

const DialogContext = React.createContext<DialogContextValue | null>(null);

function useDialogContext(component: string): DialogContextValue {
  const context = React.use(DialogContext);
  if (!context) throw new Error(`<${component}> must be used inside <Dialog> or <AlertDialog>`);
  return context;
}

/**
 * Whether the title takes focus on open (Astryx's `data-autofocus`, read after
 * `showModal()`). Alert dialogs focus their Cancel button instead.
 */
const FocusTitleContext = React.createContext(true);

type DialogProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children?: React.ReactNode;
};

function Dialog({ open: openProp, defaultOpen = false, onOpenChange, children }: DialogProps) {
  const [open, setOpen] = useControllableState({
    prop: openProp,
    defaultProp: defaultOpen,
    onChange: onOpenChange,
    caller: "Dialog"
  });
  const contentId = React.useId();
  const titleId = React.useId();
  const descriptionId = React.useId();
  const triggerRef = React.useRef<HTMLElement | null>(null);
  const [hasDescription, setHasDescription] = React.useState(false);
  const registerDescription = React.useCallback(() => {
    setHasDescription(true);
    return () => setHasDescription(false);
  }, []);

  const value = React.useMemo<DialogContextValue>(
    () => ({
      open,
      setOpen,
      contentId,
      titleId,
      descriptionId,
      hasDescription,
      registerDescription,
      triggerRef
    }),
    [open, setOpen, contentId, titleId, descriptionId, hasDescription, registerDescription]
  );

  return <DialogContext value={value}>{children}</DialogContext>;
}

type ButtonLikeProps = React.ComponentProps<"button"> & { asChild?: boolean };

function DialogTrigger({ asChild = false, onClick, ref, ...props }: ButtonLikeProps) {
  const { open, setOpen, contentId, triggerRef } = useDialogContext("DialogTrigger");
  const mergedRef = useMergedRefs(ref, triggerRef);
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      type={asChild ? undefined : "button"}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-controls={open ? contentId : undefined}
      data-state={open ? "open" : "closed"}
      data-slot="dialog-trigger"
      {...props}
      ref={mergedRef}
      onClick={(event: React.MouseEvent<HTMLButtonElement>) => {
        onClick?.(event);
        if (!event.defaultPrevented) setOpen(true);
      }}
    />
  );
}

function DialogClose({ asChild = false, onClick, ...props }: ButtonLikeProps) {
  const { setOpen } = useDialogContext("DialogClose");
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      type={asChild ? undefined : "button"}
      data-slot="dialog-close"
      {...props}
      onClick={(event: React.MouseEvent<HTMLButtonElement>) => {
        onClick?.(event);
        if (!event.defaultPrevented) setOpen(false);
      }}
    />
  );
}

const SURFACE_CLASSES =
  "text-ax-text grid gap-4 overflow-y-auto p-6 sm:max-w-lg [&>div:first-child]:contents";
/** Keeps a long title clear of the ✕ button in the corner. */
const CLOSE_BUTTON_ROOM = "[&_[data-slot=dialog-title]]:pe-8";

type DialogSurfaceProps = {
  className?: string;
  children?: React.ReactNode;
  role: "dialog" | "alertdialog";
  closeButton: boolean;
};

/**
 * The <dialog> behind DialogContent and AlertDialogContent. Mounted on first
 * open (in <body>, like Radix's portal) and kept until the root unmounts, so
 * Astryx can close it and return focus; the children only exist while open.
 */
export function DialogSurface({ className, children, role, closeButton }: DialogSurfaceProps) {
  const t = useTranslations();
  const { open, setOpen, contentId, titleId, descriptionId, hasDescription, triggerRef } =
    useDialogContext(role === "alertdialog" ? "AlertDialogContent" : "DialogContent");
  const [dialogElement, setDialogElement] = React.useState<HTMLDialogElement | null>(null);
  const [hasOpened, setHasOpened] = React.useState(open);
  if (open && !hasOpened) setHasOpened(true);
  useReturnFocus(open, triggerRef);

  if (!hasOpened) return null;

  return (
    <Portal.Root>
      <AstryxDialog
        ref={setDialogElement}
        id={contentId}
        isOpen={open}
        onOpenChange={setOpen}
        // Escape closes; a click on the backdrop never throws away input.
        purpose="form"
        role={role === "alertdialog" ? "alertdialog" : undefined}
        aria-labelledby={titleId}
        aria-describedby={hasDescription ? descriptionId : undefined}
        width="100%"
        maxHeight="calc(100dvh - 2rem)"
        padding={0}
        className={
          open ? cn(SURFACE_CLASSES, closeButton && CLOSE_BUTTON_ROOM, className) : undefined
        }
        data-slot={role === "alertdialog" ? "alert-dialog-content" : "dialog-content"}
      >
        {open ? (
          <PortalContainerContext value={dialogElement}>
            <FocusTitleContext value={role === "dialog"}>
              {children}
              {closeButton ? (
                <AstryxButton
                  variant="ghost"
                  size="sm"
                  isIconOnly
                  label={t("close")}
                  tooltip={t("close")}
                  icon={<XIcon aria-hidden="true" />}
                  onClick={() => setOpen(false)}
                  className="absolute end-3 top-3"
                />
              ) : null}
            </FocusTitleContext>
          </PortalContainerContext>
        ) : null}
      </AstryxDialog>
    </Portal.Root>
  );
}

type DialogContentProps = {
  className?: string;
  children?: React.ReactNode;
  /** The ✕ button in the corner (default on). */
  showCloseButton?: boolean;
};

function DialogContent({ className, children, showCloseButton = true }: DialogContentProps) {
  return (
    <DialogSurface role="dialog" closeButton={showCloseButton} className={className}>
      {children}
    </DialogSurface>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2 text-center sm:text-start", className)}
      {...props}
    />
  );
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & { showCloseButton?: boolean }) {
  const t = useTranslations();
  return (
    <div
      data-slot="dialog-footer"
      className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    >
      {children}
      {showCloseButton && (
        <DialogClose asChild>
          <Button variant="outline">{t("close")}</Button>
        </DialogClose>
      )}
    </div>
  );
}

/**
 * The dialog's name. In a dialog it also takes focus on open (Astryx's
 * pattern), so screen readers start at the title; alert dialogs focus Cancel.
 */
function DialogTitle({ className, children, ...props }: React.ComponentProps<"h2">) {
  const { titleId } = useDialogContext("DialogTitle");
  const focusTitle = React.use(FocusTitleContext);
  return (
    <h2
      data-slot="dialog-title"
      className={cn("text-lg leading-tight font-semibold outline-none", className)}
      {...props}
      id={titleId}
      tabIndex={focusTitle ? -1 : undefined}
      data-autofocus={focusTitle ? "" : undefined}
    >
      {children}
    </h2>
  );
}

function DialogDescription({ className, ...props }: React.ComponentProps<"p">) {
  const { descriptionId, registerDescription } = useDialogContext("DialogDescription");
  React.useLayoutEffect(registerDescription, [registerDescription]);
  return (
    <p
      data-slot="dialog-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
      id={descriptionId}
    />
  );
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  useDialogContext
};
