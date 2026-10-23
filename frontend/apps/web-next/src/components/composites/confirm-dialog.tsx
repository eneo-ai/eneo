"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { useMediaQuery, useMergedRefs } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter, Stack } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "next-intl";
import {
  cloneElement,
  isValidElement,
  useId,
  useRef,
  useState,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
  type Ref,
  type RefObject
} from "react";
import { createPortal, flushSync } from "react-dom";
import { TextInput } from "@astryxdesign/core/TextInput";
// Not shadcn: the focus return every Astryx Dialog in the app shares (menu
// openers, Safari's unfocused clicks, an opener that is gone).
import { useReturnFocus } from "@/components/ui/dialog-focus";

/** Astryx AlertDialog's breakpoint for stacking its actions. */
const SMALL_SCREEN_QUERY = "(max-width: 640px)";

type ConfirmSurfaceProps = {
  open: boolean;
  /** Asked to close (Escape or Cancel); the owner decides. */
  onRequestClose: () => void;
  title: string;
  description: string;
  confirmLabel: string;
  variant: "default" | "destructive";
  busy: boolean;
  onConfirm: () => void;
  dialogId: string;
  triggerRef: RefObject<HTMLElement | null>;
  children?: ReactNode;
};

/**
 * The alert dialog both confirmations render: Astryx AlertDialog's anatomy
 * (role "alertdialog", the title and the consequence linked, no dismissal
 * from the backdrop, Escape cancels, Cancel focused on open, the destructive
 * action above Cancel on narrow screens) composed from Astryx Dialog, since
 * AlertDialog takes no field and disables its action while it loads. Busy, the
 * confirm button stays enabled (`isLoading` + `isInterruptible`) so it keeps
 * focus, and Cancel waits.
 *
 * Mounted in <body> on first open and kept after it closes, so Astryx can
 * close it and return focus; the content only exists while open.
 */
function ConfirmSurface({
  open,
  onRequestClose,
  title,
  description,
  confirmLabel,
  variant,
  busy,
  onConfirm,
  dialogId,
  triggerRef,
  children
}: ConfirmSurfaceProps) {
  const t = useTranslations();
  const titleId = useId();
  const descriptionId = useId();
  const isSmallScreen = useMediaQuery(SMALL_SCREEN_QUERY);
  const [mounted, setMounted] = useState(open);
  if (open && !mounted) setMounted(true);
  useReturnFocus(open, triggerRef);

  if (!mounted) return null;

  const cancel = (
    <Button
      key="cancel"
      variant="ghost"
      label={t("cancel")}
      isDisabled={busy}
      width={isSmallScreen ? "100%" : undefined}
      onClick={onRequestClose}
      // Astryx Dialog focuses [data-autofocus] after showModal(): the least
      // destructive choice, whatever the visual order.
      data-autofocus=""
    />
  );
  const action = (
    <Button
      key="action"
      variant={variant === "destructive" ? "destructive" : "primary"}
      label={confirmLabel}
      isLoading={busy}
      isInterruptible
      width={isSmallScreen ? "100%" : undefined}
      onClick={() => {
        if (!busy) onConfirm();
      }}
    />
  );

  return createPortal(
    <Dialog
      id={dialogId}
      isOpen={open}
      onOpenChange={(next) => {
        if (!next) onRequestClose();
      }}
      // Escape closes; a click on the backdrop never does.
      purpose="form"
      role="alertdialog"
      // Only while open: a closed dialog has no title or description to point at.
      aria-labelledby={open ? titleId : undefined}
      aria-describedby={open ? descriptionId : undefined}
      width={440}
    >
      <Layout
        height="auto"
        content={
          open ? (
            <LayoutContent>
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                  <Heading level={2} id={titleId}>
                    {title}
                  </Heading>
                  <Text type="body" color="secondary" as="p" id={descriptionId}>
                    {description}
                  </Text>
                </div>
                {children}
              </div>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <Stack
                direction={isSmallScreen ? "vertical" : "horizontal"}
                gap={2}
                hAlign={isSmallScreen ? "stretch" : "end"}
                wrap={isSmallScreen ? "nowrap" : "wrap"}
              >
                {isSmallScreen ? [action, cancel] : [cancel, action]}
              </Stack>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>,
    document.body
  );
}

/**
 * Controlled confirmation dialog without a trigger, for actions launched from
 * dropdown menus (the menu closes before the dialog opens; render it outside
 * the menu). While `pending`, neither Cancel nor Escape closes it, and the
 * confirm button stays enabled (so it keeps focus) but ignores a press.
 * `children` show below the description (what the action will change).
 */
export function ConfirmDialogControlled({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  variant = "destructive",
  pending,
  onConfirm,
  children
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  variant?: "default" | "destructive";
  pending?: boolean;
  onConfirm: () => void;
  children?: ReactNode;
}) {
  const dialogId = useId();
  const noTrigger = useRef<HTMLElement | null>(null);
  return (
    <ConfirmSurface
      open={open}
      onRequestClose={() => {
        if (!pending) onOpenChange(false);
      }}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      variant={variant}
      busy={pending ?? false}
      onConfirm={onConfirm}
      dialogId={dialogId}
      triggerRef={noTrigger}
    >
      {children}
    </ConfirmSurface>
  );
}

type TriggerProps = {
  type?: string;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  ref?: Ref<HTMLElement>;
};

/**
 * The caller's trigger (one element that passes `onClick`, `ref` and ARIA
 * attributes to its button, as Radix's `asChild` asked) wired to open the
 * dialog: type="button" unless it has its own, so it never submits a form.
 */
function DialogTrigger({
  trigger,
  open,
  dialogId,
  triggerRef,
  onOpen
}: {
  trigger: ReactNode;
  open: boolean;
  dialogId: string;
  triggerRef: RefObject<HTMLElement | null>;
  onOpen: () => void;
}) {
  const element = isValidElement<TriggerProps>(trigger) ? trigger : null;
  const ref = useMergedRefs(element?.props.ref, triggerRef);
  if (!element) return trigger;
  return cloneElement(element as ReactElement<TriggerProps & Record<string, unknown>>, {
    type: element.props.type ?? "button",
    "aria-haspopup": "dialog",
    "aria-expanded": open,
    "aria-controls": open ? dialogId : undefined,
    ref,
    onClick: (event: MouseEvent<HTMLElement>) => {
      element.props.onClick?.(event);
      if (event.defaultPrevented) return;
      // Safari does not focus a button on click: focused, it is where focus
      // returns when the dialog closes.
      event.currentTarget.focus();
      onOpen();
    }
  });
}

/**
 * Confirmation dialog for destructive actions. With `confirmValue` set, the
 * user must type it (e.g. the resource name): confirming without it says so at
 * the field, which takes focus. While the action runs it cannot be closed and
 * the confirm button keeps focus; when it fails (the caller reports the error)
 * the dialog stays open with what the user typed.
 */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  confirmValue,
  confirmValueLabel,
  pending = false,
  onConfirm
}: {
  trigger: ReactNode;
  title: string;
  description: string;
  confirmLabel: string;
  confirmValue?: string;
  confirmValueLabel?: string;
  pending?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const t = useTranslations();
  const dialogId = useId();
  const triggerRef = useRef<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [running, setRunning] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = pending || running;
  const blocked = confirmValue !== undefined && typed !== confirmValue;
  const problem =
    submitted && blocked ? t("form_problem_confirm_mismatch", { value: confirmValue }) : null;

  function close() {
    setOpen(false);
    setTyped("");
    setSubmitted(false);
  }

  async function confirm() {
    if (busy) return;
    if (blocked) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      inputRef.current?.focus();
      return;
    }
    setRunning(true);
    try {
      await onConfirm();
    } catch {
      // The caller reports the failure (a toast from its mutation); keep the
      // dialog open so the user can retry or cancel.
      return;
    } finally {
      setRunning(false);
    }
    close();
  }

  return (
    <>
      <DialogTrigger
        trigger={trigger}
        open={open}
        dialogId={dialogId}
        triggerRef={triggerRef}
        onOpen={() => setOpen(true)}
      />
      <ConfirmSurface
        open={open}
        onRequestClose={() => {
          if (!busy) close();
        }}
        title={title}
        description={description}
        confirmLabel={confirmLabel}
        variant="destructive"
        busy={busy}
        onConfirm={() => void confirm()}
        dialogId={dialogId}
        triggerRef={triggerRef}
      >
        {confirmValue !== undefined ? (
          <TextInput
            ref={inputRef}
            label={confirmValueLabel ?? confirmValue}
            value={typed}
            placeholder={confirmValue}
            autoComplete="off"
            onChange={setTyped}
            status={problem ? { type: "error", message: problem } : undefined}
          />
        ) : null}
      </ConfirmSurface>
    </>
  );
}
