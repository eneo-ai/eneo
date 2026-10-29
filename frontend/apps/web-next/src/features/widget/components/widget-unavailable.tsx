"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useSyncExternalStore } from "react";
import { createEmbedBridge, type EmbedBridge } from "../embed-bridge";

const subscribeNever = () => () => {};

/**
 * The panel's content for a paused, archived or unknown widget. It joins the
 * loader's protocol like the chat does: focus moves to the notice when the
 * panel opens, so a screen reader reads it, and the visitor closes it from
 * here with the button or Escape.
 */
export function WidgetNotice({ hostOrigin }: { hostOrigin: string | null }) {
  const t = useTranslations();
  const heading = useRef<HTMLHeadingElement>(null);
  const bridge = useRef<EmbedBridge | null>(null);
  const embedded = useSyncExternalStore(
    subscribeNever,
    () => hostOrigin !== null && window.parent !== window,
    () => false
  );

  useEffect(() => {
    const created = createEmbedBridge({
      hostOrigin,
      handlers: { onOpen: () => heading.current?.focus() }
    });
    bridge.current = created;
    created.ready();
    const onKeydown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || !created.embedded) return;
      event.preventDefault();
      created.close();
    };
    window.addEventListener("keydown", onKeydown);
    return () => {
      window.removeEventListener("keydown", onKeydown);
      created.destroy();
      bridge.current = null;
    };
  }, [hostOrigin]);

  return (
    // Every state of the page is its main landmark, like the chat itself.
    <main className="bg-ax-surface text-ax-text fixed inset-0 flex flex-col items-center justify-center gap-2 p-6">
      {embedded && (
        <button
          type="button"
          className="widget-notice-close hover:bg-ax-hover absolute top-3 right-3"
          onClick={() => bridge.current?.close()}
          aria-label={t("widget_close")}
          title={t("widget_close")}
        >
          <X className="size-5" aria-hidden="true" />
        </button>
      )}
      <h1 ref={heading} className="text-base font-semibold" tabIndex={-1}>
        {t("widget_not_available_title")}
      </h1>
      <p className="text-ax-text-secondary text-center text-sm">{t("widget_not_available_body")}</p>
    </main>
  );
}
