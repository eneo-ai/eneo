"use client";

import { Button } from "@astryxdesign/core/Button";
import { useClipboard } from "@astryxdesign/core/hooks";
import { Check, Copy, ExternalLink } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { TextInput } from "@/components/astryx/text-input";
import { toast } from "@/lib/toast";
import type { Widget } from "./autosave";
import { docsUrl } from "./docs";
import {
  floatingSnippet,
  pinnedSnippet,
  standaloneUrl,
  type LoaderRelease,
  type SnippetOptions
} from "./snippet";

function CopyButton({ text, label }: { text: string | null; label: string }) {
  const t = useTranslations();
  const { copy, isCopied } = useClipboard({ announce: t("copied_to_clipboard") });
  return (
    <Button
      label={isCopied ? t("copied_to_clipboard") : label}
      icon={
        isCopied ? (
          <Check className="size-4" aria-hidden="true" />
        ) : (
          <Copy className="size-4" aria-hidden="true" />
        )
      }
      isDisabled={!text}
      isInterruptible
      clickAction={async () => {
        if (text && !(await copy(text))) toast.error(t("chat_copy_failed"));
      }}
    />
  );
}

/**
 * What the web editor pastes into the site: the floating loader snippet by
 * default, a pinned+SRI variant on request, and the stand-alone page URL.
 */
export function WidgetSnippet({
  widget,
  release,
  origin
}: {
  widget: Widget;
  release: LoaderRelease | null;
  origin: string;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const titleId = useId();
  const [pinned, setPinned] = useState(false);

  const options: SnippetOptions = {
    origin,
    publicId: widget.public_id,
    language: widget.language,
    release
  };
  const snippet = pinned ? pinnedSnippet(options) : floatingSnippet(options);
  const standalone = standaloneUrl(options);

  return (
    <section
      aria-labelledby={titleId}
      className="bg-ax-card border-ax-border flex flex-col gap-3 rounded-xl border p-4"
    >
      <h2 id={titleId} className="text-base font-semibold">
        {t("widget_admin_snippet")}
      </h2>
      <p className="text-ax-text-secondary text-sm">{t("widget_admin_snippet_description")}</p>
      <a
        className="text-ax-text-accent inline-flex w-fit items-center gap-1 text-sm underline underline-offset-2"
        href={docsUrl("guides/embed-widget", locale, "for-the-website-team")}
        target="_blank"
        rel="noreferrer"
      >
        {t("widget_admin_snippet_guide")}
        <ExternalLink className="size-3.5" aria-hidden="true" />
      </a>

      {widget.status !== "active" && (
        <p className="bg-ax-warning-muted text-ax-text rounded-lg px-3 py-2 text-sm">
          {t("widget_admin_snippet_inactive")}
        </p>
      )}

      {snippet ? (
        <pre
          className="bg-ax-muted text-ax-text rounded-lg p-3 font-mono text-xs break-all whitespace-pre-wrap"
          aria-label={t("widget_admin_snippet")}
        >
          <code>{snippet}</code>
        </pre>
      ) : (
        <p className="bg-ax-warning-muted text-ax-text rounded-lg px-3 py-2 text-sm">
          {t("widget_admin_snippet_not_built")}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Switch
          label={t("widget_admin_snippet_pinned")}
          value={pinned}
          onChange={setPinned}
          isDisabled={!release}
        />
        <CopyButton text={snippet} label={t("widget_admin_copy")} />
      </div>
      {pinned && (
        <p className="text-ax-text-secondary text-sm">{t("widget_admin_snippet_pinned_help")}</p>
      )}

      <h3 className="mt-2 text-sm font-medium">{t("widget_admin_standalone")}</h3>
      <p className="text-ax-text-secondary text-sm">{t("widget_admin_standalone_description")}</p>
      <div className="flex items-end gap-2">
        <TextInput
          label={t("widget_admin_standalone")}
          isLabelHidden
          value={standalone}
          isReadOnly
          width="100%"
        />
        <CopyButton text={standalone} label={t("widget_admin_copy")} />
      </div>
    </section>
  );
}
