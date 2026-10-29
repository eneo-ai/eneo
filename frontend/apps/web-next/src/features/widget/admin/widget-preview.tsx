"use client";

import { Button } from "@astryxdesign/core/Button";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { toastApiError } from "@/lib/api/toast";
import { previewEmbedPath } from "../preview";
import type { Widget } from "./autosave";
import { widgetApi } from "./queries";
import { useAppScheme } from "./use-app-scheme";

type Scheme = "auto" | "light" | "dark";

// setTimeout fires at once for longer delays.
const MAX_TIMEOUT = 2_147_483_647;

/**
 * The real embed page in an iframe, driven by a preview token so drafts work
 * too. Reloads after every saved change; re-mints the token when a change
 * bumps the widget's token generation and shortly before it expires.
 */
export function WidgetPreview({ widget }: { widget: Widget }) {
  const t = useTranslations();
  const titleId = useId();
  const [token, setToken] = useState<string | null>(null);
  const [tokenGeneration, setTokenGeneration] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [scheme, setScheme] = useState<Scheme>("auto");
  const [mobile, setMobile] = useState(false);
  // "Auto" follows what the admin sees in Eneo right now, also after a theme switch.
  const appScheme = useAppScheme();

  const lang = widget.language === "en" ? "en" : "sv";
  // A widget pinned to light or dark previews that way whatever the toggle says.
  const pinnedScheme =
    widget.theme.color_scheme === "light" || widget.theme.color_scheme === "dark"
      ? widget.theme.color_scheme
      : null;

  const renewal = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const live = useRef({
    id: widget.id,
    generation: widget.token_generation,
    status: widget.status
  });
  useEffect(() => {
    live.current = { id: widget.id, generation: widget.token_generation, status: widget.status };
  }, [widget.id, widget.token_generation, widget.status]);
  const destroyed = useRef(false);

  const mint = useRef(async (): Promise<void> => {});
  async function mintNow() {
    // A token is minted for the generation current when it was requested. A
    // rules save can advance the generation (and start another mint) before
    // this one answers; a late answer is then stale and the backend would
    // reject it, so it must neither replace the current token nor be
    // recorded as covering the new generation.
    const requested = { id: live.current.id, generation: live.current.generation };
    const current = () =>
      requested.id === live.current.id && requested.generation === live.current.generation;
    clearTimeout(renewal.current);
    setFailed(false);
    try {
      const minted = await widgetApi.previewToken(requested.id);
      if (!current() || destroyed.current) return;
      setToken(minted.token);
      setTokenGeneration(requested.generation);
      // The framed chat sends this token with every request, so it is renewed
      // a minute before it expires rather than left to die in the frame.
      clearTimeout(renewal.current);
      const renewIn = Math.max(minted.expires_in - 60, minted.expires_in / 2);
      renewal.current = setTimeout(
        () => {
          if (live.current.status !== "archived") void mint.current();
        },
        Math.min(renewIn * 1000, MAX_TIMEOUT)
      );
    } catch (error) {
      if (!current() || destroyed.current) return;
      setFailed(true);
      toastApiError(error, t);
    }
  }

  // The handlers below call the latest mint, not the one of the render they
  // were created in.
  useEffect(() => {
    mint.current = mintNow;
  });

  // One automatic attempt per generation: every edit hands this effect a new
  // widget, and a failed mint is retried with the reload button, not per
  // keystroke.
  const attempted = useRef<number | null>(null);
  useEffect(() => {
    if (widget.status === "archived") return;
    const generation = widget.token_generation;
    if (tokenGeneration === generation || attempted.current === generation) return;
    attempted.current = generation;
    void mint.current();
  }, [widget.status, widget.token_generation, tokenGeneration]);
  useEffect(() => {
    destroyed.current = false;
    return () => {
      destroyed.current = true;
      clearTimeout(renewal.current);
    };
  }, []);

  let src: string | null = null;
  if (token) {
    const path = previewEmbedPath(widget.public_id, token, lang);
    const effective = pinnedScheme ?? (scheme === "auto" ? appScheme : scheme);
    // updated_at forces a reload after every saved change.
    src = path.replace("#", `&scheme=${effective}&v=${encodeURIComponent(widget.updated_at)}#`);
  }

  return (
    <section
      aria-labelledby={titleId}
      className="bg-ax-card border-ax-border flex flex-col gap-3 rounded-xl border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={titleId} className="text-base font-semibold">
          {t("widget_admin_preview")}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <ToggleButtonGroup
            label={t("widget_admin_preview_scheme")}
            size="sm"
            value={pinnedScheme ?? scheme}
            onChange={(next) => {
              if (next === "auto" || next === "light" || next === "dark") setScheme(next);
            }}
          >
            <ToggleButton
              value="auto"
              label={t("widget_admin_scheme_auto")}
              isDisabled={pinnedScheme !== null}
            />
            <ToggleButton
              value="light"
              label={t("widget_admin_scheme_light")}
              isDisabled={pinnedScheme !== null}
            />
            <ToggleButton
              value="dark"
              label={t("widget_admin_scheme_dark")}
              isDisabled={pinnedScheme !== null}
            />
          </ToggleButtonGroup>
          <ToggleButton
            size="sm"
            label={t("widget_admin_preview_mobile")}
            isPressed={mobile}
            onPressedChange={setMobile}
          />
          <Button
            size="sm"
            label={t("widget_admin_preview_reload")}
            onClick={() => void mint.current()}
          />
        </div>
      </div>
      <p className="text-ax-text-secondary text-sm">
        {pinnedScheme
          ? t("widget_admin_preview_scheme_pinned", {
              scheme:
                pinnedScheme === "dark"
                  ? t("widget_admin_scheme_dark")
                  : t("widget_admin_scheme_light")
            })
          : t("widget_admin_preview_description")}
      </p>

      <div className="bg-ax-muted flex justify-center rounded-lg p-3">
        {failed ? (
          <p role="alert" className="text-ax-red py-10 text-sm">
            {t("widget_admin_preview_failed")}
          </p>
        ) : src ? (
          // Same origin as this page: a sandbox attribute would be no barrier here, so none is pretended.
          <iframe
            src={src}
            title={t("widget_admin_preview_frame_title")}
            className="border-ax-border bg-ax-surface rounded-lg border shadow"
            style={{ width: mobile ? "375px" : "100%", height: "600px" }}
          />
        ) : (
          <p className="text-ax-text-secondary py-10 text-sm">{t("widget_preview_loading")}</p>
        )}
      </div>
    </section>
  );
}
