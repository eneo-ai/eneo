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
import { createPortal } from "react-dom";
import { Toaster as Sonner, type ToasterProps } from "sonner";
// Sonner's styles ship as a same-origin stylesheet (allowed by style-src 'self').
// Its runtime <style> injection carries no CSP nonce, so it is patched out in
// frontend/patches/sonner@*.patch.
import "sonner/dist/styles.css";
import { useLiveRegionsIn, useTopModalDialog } from "@/components/ui/open-modals";

/**
 * The app's toasts (sonner): a polite live region at the edge of the page.
 *
 * A modal dialog makes the rest of the page inert and covers it, so a toast
 * shown while one is open (a failed save, say) would be dimmed, unclickable
 * and never announced. While a modal is open (open-modals.ts), a second
 * toaster inside it shows the same toasts (sonner's store is shared) in the
 * dialog's layer, like the nested ToastViewport Astryx uses inside dialogs.
 * Astryx's own announcements (useAnnounce) move into it too.
 */
const Toaster = ({ ...props }: ToasterProps) => {
  const t = useTranslations();
  const { theme = "system" } = useTheme();
  const modal = useTopModalDialog();
  useLiveRegionsIn(modal);

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
