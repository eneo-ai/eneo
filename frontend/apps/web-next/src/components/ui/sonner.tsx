"use client";

import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Toaster as Sonner, type ToasterProps } from "sonner";
// Sonner's styles ship as a same-origin stylesheet (allowed by style-src 'self').
// Its runtime <style> injection carries no CSP nonce, so it is patched out in
// frontend/patches/sonner@*.patch.
import "sonner/dist/styles.css";

function isModal(dialog: HTMLDialogElement): boolean {
  // aria-modal: Astryx marks its modal dialogs, and jsdom never matches :modal.
  return dialog.matches(":modal") || dialog.getAttribute("aria-modal") === "true";
}

/** The modal <dialog> opened last, while one is open. */
function useTopModalDialog(): HTMLDialogElement | null {
  const [top, setTop] = useState<HTMLDialogElement | null>(null);

  useEffect(() => {
    const openOrder: HTMLDialogElement[] = [];
    let frame = 0;
    const update = () => {
      frame = 0;
      const open = Array.from(document.querySelectorAll("dialog[open]")).filter(
        (dialog): dialog is HTMLDialogElement =>
          dialog instanceof HTMLDialogElement && isModal(dialog)
      );
      for (let index = openOrder.length - 1; index >= 0; index -= 1) {
        if (!open.includes(openOrder[index]!)) openOrder.splice(index, 1);
      }
      for (const dialog of open) if (!openOrder.includes(dialog)) openOrder.push(dialog);
      setTop(openOrder.at(-1) ?? null);
    };
    // Dialogs open, close and unmount anywhere in the page; one check per frame.
    const observer = new MutationObserver(() => {
      frame ||= requestAnimationFrame(update);
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["open"]
    });
    update();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  return top;
}

/**
 * The app's toasts (sonner): a polite live region at the edge of the page.
 *
 * A modal dialog makes the rest of the page inert and covers it, so a toast
 * shown while one is open (a failed save, say) would be dimmed, unclickable
 * and never announced. While a modal is open, a second toaster inside it shows
 * the same toasts (sonner's store is shared) in the dialog's layer, like the
 * nested ToastViewport Astryx uses inside dialogs.
 */
const Toaster = ({ ...props }: ToasterProps) => {
  const t = useTranslations();
  const { theme = "system" } = useTheme();
  const modal = useTopModalDialog();

  const toaster = (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      containerAriaLabel={t("notifications")}
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)"
        } as React.CSSProperties
      }
      {...props}
    />
  );

  return (
    <>
      {toaster}
      {modal
        ? createPortal(
            // Out of the dialog's layout; the toasts themselves are fixed.
            <div className="absolute size-0">{toaster}</div>,
            modal
          )
        : null}
    </>
  );
};

export { Toaster };
