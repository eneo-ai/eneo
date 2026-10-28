import { useTranslations } from "next-intl";
import { useState } from "react";
import type { PersonaView } from "../persona";

/**
 * Who is answering: the persona's avatar, name and an AI marker, above the
 * welcome text and above every answer. The byline is the visible form of the
 * "Assistant:" prefix screen readers got before, so it is read once ("Sigge,
 * AI-assistent") and never twice. The avatar is decorative; the name beside it
 * carries the meaning (WCAG 1.1.1). The AI marker is not a setting (AI Act
 * article 50).
 */
export function WidgetPersonaByline({ persona }: { persona: PersonaView }) {
  const t = useTranslations();
  // An avatar the browser cannot load (gone, blocked) falls back to the
  // monogram instead of a broken image.
  const [imageFailed, setImageFailed] = useState(false);
  const showImage = persona.avatarUrl !== null && !imageFailed;
  return (
    <p className="widget-byline mb-1 flex items-center gap-2">
      <span
        className="widget-avatar size-6 shrink-0 overflow-hidden rounded-full text-xs"
        aria-hidden="true"
      >
        {showImage ? (
          // The proxy under this origin serves the upload; nothing else fits next/image.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            className="size-full object-cover"
            src={persona.avatarUrl ?? undefined}
            alt=""
            referrerPolicy="no-referrer"
            onError={() => setImageFailed(true)}
          />
        ) : (
          persona.monogram
        )}
      </span>
      <span className="flex min-w-0 items-center gap-1.5">
        <span className="text-ax-text text-sm font-semibold break-words">{persona.name}</span>
        <span className="widget-ai-chip" title={t("widget_persona_ai_assistant")}>
          <span aria-hidden="true">{t("widget_persona_ai_chip")}</span>
          <span className="sr-only">{t("widget_persona_ai_assistant")}</span>
        </span>
      </span>
    </p>
  );
}
