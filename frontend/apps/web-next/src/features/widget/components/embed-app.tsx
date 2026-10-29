"use client";

import { createWidgetClient, type WidgetPublicConfig } from "@eneo/eneo-js";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { DARK_SURFACE, LIGHT_SURFACE, contrastRatio, readableOn, themeColors } from "../contrast";
import { personaView } from "../persona";
import type { VisitorSession } from "../visitor-session";
import { useEmbedScheme } from "./embed-providers";
import { WidgetChat } from "./widget-chat";
import "../widget.css";

type Scheme = "light" | "dark" | "auto";

/**
 * The visitor API is proxied under this page's own origin (the browser
 * never reaches the backend). The client wants an absolute base, which the
 * server does not know for sure (a reverse proxy may front the app) and the
 * page must not guess: requests are made relative, against the origin the
 * page actually runs on, by taking this placeholder off again.
 */
const PLACEHOLDER_ORIGIN = "http://eneo-embed.invalid";

function sameOriginFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  return fetch(url.replace(PLACEHOLDER_ORIGIN, ""), init);
}

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
 * configuration is known (from the server for active widgets, client-side
 * with a preview token for drafts).
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

  // The same client on the server and in the browser, so the page hydrates
  // as rendered; it only ever makes requests in the browser.
  const client = useMemo(
    () =>
      createWidgetClient({
        baseUrl: PLACEHOLDER_ORIGIN,
        publicId,
        getToken: () => holder.get()?.token ?? null,
        fetch: sameOriginFetch
      }),
    [publicId, holder]
  );

  // A widget pinned to light or dark stays that way; "auto" follows the host
  // page (its `scheme` query parameter first, later `theme` messages) and
  // finally the visitor's system setting.
  const pinnedScheme = config.theme.color_scheme ?? "auto";
  const { setMode } = useEmbedScheme();
  const systemQuery = useRef<MediaQueryList | null>(null);

  // Whether the panel is dark right now, so the widget's own colours can
  // switch with it. Starts from what the server rendered.
  const [dark, setDark] = useState(
    () => (pinnedScheme === "auto" ? hostScheme : pinnedScheme) === "dark"
  );

  const applyScheme = useCallback(
    (scheme: Scheme) => {
      const effective = pinnedScheme === "auto" ? scheme : pinnedScheme;
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
      if (!document.documentElement.hasAttribute("data-theme")) setDark(query.matches);
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
        onSession={holder.set}
        onTheme={applyScheme}
      />
    </div>
  );
}
