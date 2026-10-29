"use client";

import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { toastApiError } from "@/lib/api/toast";
import type { Widget } from "./autosave";
import { widgetApi } from "./queries";
import { loaderUrl, type LoaderRelease } from "./snippet";
import { useAppScheme } from "./use-app-scheme";

function loadLoader(src: string): Promise<void> {
  if (customElements.get("eneo-widget")) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("loader"));
    document.head.appendChild(script);
  });
}

/**
 * "Test in Eneo": mounts the real loader script and an <eneo-widget> element on
 * this very page, so the launcher, panel, focus handling and keyboard flow can
 * be tried exactly as on a host site before the snippet goes anywhere.
 */
export function WidgetLiveTest({
  widget,
  release
}: {
  widget: Widget;
  /** The loader build this installation serves; null when it has none. */
  release: LoaderRelease | null;
}) {
  const t = useTranslations();
  const titleId = useId();
  const appScheme = useAppScheme();
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [loading, setLoading] = useState(false);
  // A start that is still waiting for its token and loader when the editor
  // stops it or leaves the page must not mount anything afterwards: the
  // launcher would land on whatever page the admin navigated to, with the
  // removal control gone. Each start belongs to one generation; stop() and
  // unmounting move on.
  const generation = useRef(0);
  const mounted = useRef<HTMLElement | null>(null);

  useEffect(() => {
    return () => {
      generation.current += 1;
      mounted.current?.remove();
      mounted.current = null;
    };
  }, []);

  async function start() {
    if (!release || loading) return;
    const run = ++generation.current;
    setLoading(true);
    try {
      const [{ token }] = await Promise.all([
        widgetApi.previewToken(widget.id),
        loadLoader(loaderUrl(window.location.origin, release.channel))
      ]);
      if (run !== generation.current) return;
      const created = document.createElement("eneo-widget");
      created.setAttribute("widget-id", widget.public_id);
      created.setAttribute("preview", token);
      created.setAttribute("position", widget.theme.position ?? "bottom-right");
      // Follow the admin's current Eneo theme unless the widget pins a scheme.
      const pinned = widget.theme.color_scheme;
      created.setAttribute(
        "color-scheme",
        pinned === "light" || pinned === "dark" ? pinned : appScheme
      );
      if (widget.language && widget.language !== "auto") {
        created.setAttribute("lang", widget.language);
      }
      // The launcher takes the widget's colours from the embed page itself.
      created.style.setProperty("--eneo-widget-radius", `${widget.theme.radius ?? 12}px`);
      document.body.appendChild(created);
      mounted.current = created;
      setElement(created);
      (created as HTMLElement & { openPanel?: () => void }).openPanel?.();
    } catch (error) {
      if (run !== generation.current) return;
      toastApiError(error, t);
    } finally {
      if (run === generation.current) setLoading(false);
    }
  }

  function stop() {
    generation.current += 1;
    setLoading(false);
    mounted.current?.remove();
    mounted.current = null;
    setElement(null);
  }

  return (
    <section
      aria-labelledby={titleId}
      className="bg-ax-card border-ax-border flex flex-col gap-3 rounded-xl border p-4"
    >
      <h2 id={titleId} className="text-base font-semibold">
        {t("widget_admin_live_test")}
      </h2>
      <p className="text-ax-text-secondary text-sm">{t("widget_admin_live_test_description")}</p>
      {!release && (
        <p className="bg-ax-warning-muted text-ax-text rounded-lg px-3 py-2 text-sm">
          {t("widget_admin_snippet_not_built")}
        </p>
      )}
      <div>
        {element ? (
          <Button label={t("widget_admin_live_test_stop")} onClick={stop} />
        ) : (
          <Button
            variant="primary"
            label={t("widget_admin_live_test_start")}
            isLoading={loading}
            isInterruptible
            isDisabled={!release}
            clickAction={start}
          />
        )}
      </div>
    </section>
  );
}
