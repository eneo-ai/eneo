"use client";

import { createWidgetClient, type WidgetPublicConfig } from "@eneo/eneo-js";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  DARK_SURFACE,
  LIGHT_SURFACE,
  contrastRatio,
  readableOn,
  themeColors
} from "@eneo/eneo-js/widgets/contrast";
import { personaView } from "../persona";
import type { VisitorSession } from "@eneo/eneo-js/widgets/visitor-session";
import { useEmbedScheme } from "./embed-providers";
import { WidgetChat } from "./widget-chat";
import "../widget.css";

type Scheme = "light" | "dark" | "auto";

function sessionHolder() {
  let session: VisitorSession | null = null;
  return {
    get: () => session,
    set: (created: VisitorSession) => {
      session = created;
    }
  };
}

/**
 * Boots the chat for one widget: the widget client, the colour scheme and
 * the widget's own colours. Rendered by the embed page once the
 * configuration is known (loaded by the route for active widgets, or with a
 * preview token from the browser fragment for drafts).
 */
export function EmbedApp({
  config,
  publicId,
  hostOrigin,
  hostScheme,
  previewToken = null
}: {
  config: WidgetPublicConfig;
  publicId: string;
  hostOrigin: string | null;
  hostScheme: Scheme | null;
  previewToken?: string | null;
}) {
  // The chat creates the visitor session once it mounts; the client reads
  // the token from it on every request (a holder with a setter, as a
  // closure over a ref would read it during render).
  const [holder] = useState(() => sessionHolder());

  // The visitor client always omits cookies and uses its own bearer token.
  const client = useMemo(
    () =>
      createWidgetClient({
        baseUrl: location.origin,
        publicId,
        getToken: () => holder.get()?.token ?? null
      }),
    [publicId, holder]
  );

  // A widget pinned to light or dark stays that way; "auto" follows the host
  // page (its `scheme` query parameter first, later `theme` messages) and
  // finally the visitor's system setting.
  const pinnedScheme = config.theme.color_scheme ?? "auto";
  const { setMode } = useEmbedScheme();
  const systemQuery = useRef<MediaQueryList | null>(null);
  const effectiveScheme = useRef<Scheme>(
    pinnedScheme === "auto" ? (hostScheme ?? "auto") : pinnedScheme
  );

  // Whether the panel is dark right now, so the widget's own colours can
  // switch with it. Starts from the scheme FastAPI selected.
  const [dark, setDark] = useState(
    () => (pinnedScheme === "auto" ? hostScheme : pinnedScheme) === "dark"
  );

  const applyScheme = useCallback(
    (scheme: Scheme) => {
      const effective = pinnedScheme === "auto" ? scheme : pinnedScheme;
      effectiveScheme.current = effective;
      setMode(effective === "auto" ? "system" : effective);
      setDark(
        effective === "auto" ? (systemQuery.current?.matches ?? false) : effective === "dark"
      );
    },
    [pinnedScheme, setMode]
  );

  useEffect(() => {
    const query = matchMedia("(prefers-color-scheme: dark)");
    systemQuery.current = query;
    const followSystem = () => {
      if (effectiveScheme.current === "auto") setDark(query.matches);
    };
    query.addEventListener("change", followSystem);
    applyScheme(hostScheme ?? "auto");
    return () => query.removeEventListener("change", followSystem);
  }, [applyScheme, hostScheme]);

  // The widget's own colours as CSS variables, per scheme; text colours are
  // derived so the combination always reads (WCAG 1.4.3 / 1.4.11).
  const { accent, header } = themeColors(config.theme, dark);
  // The focus ring takes the widget's own colour where it reads against the
  // panel (3:1, WCAG 1.4.11); otherwise the text colour, which always does.
  const focus = contrastRatio(accent, dark ? DARK_SURFACE : LIGHT_SURFACE) >= 3 ? accent : null;
  // The persona's monogram is small text on the avatar: it takes the accent
  // only where the derived text colour reaches 4.5:1 on it (WCAG 1.4.3);
  // otherwise the byline's neutral plate.
  const avatarOnAccent = contrastRatio(readableOn(accent), accent) >= 4.5;
  const persona = useMemo(() => personaView(config), [config]);

  const style = {
    "--widget-accent": accent,
    "--widget-on-accent": readableOn(accent),
    "--widget-header": header ?? undefined,
    "--widget-on-header": header ? readableOn(header) : undefined,
    "--widget-focus": focus ?? undefined,
    "--widget-radius": `${config.theme.radius ?? 12}px`,
    "--widget-avatar-bg": avatarOnAccent ? accent : undefined,
    "--widget-avatar-fg": avatarOnAccent ? readableOn(accent) : undefined
  } as CSSProperties;

  return (
    <div className="widget-root bg-ax-surface fixed inset-0 flex flex-col" style={style}>
      <WidgetChat
        config={config}
        client={client}
        hostOrigin={hostOrigin}
        previewToken={previewToken}
        persona={persona}
        tintedHeader={!!header}
        onSession={holder.set}
        onTheme={applyScheme}
      />
    </div>
  );
}
