"use client";

import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { cjk } from "@streamdown/cjk";
import { createCodePlugin } from "@streamdown/code";
import type { ComponentProps } from "react";
import { useTranslations } from "next-intl";
import { memo, useCallback, useMemo } from "react";
import { Streamdown } from "streamdown";
import { answerRehypePlugins, answerRemarkPlugins } from "./answer-markdown";
import { mathPlugin } from "./math";
import { AnswerDiagram } from "./diagram";
import "katex/dist/katex.min.css";
import "./message.css";
import {
  markdownComponents,
  rehypeCodeBlockRegions,
  useStreamdownTranslations
} from "./markdown-components";

export type MessageResponseProps = ComponentProps<typeof Streamdown>;

/**
 * Typography of assistant answers (and quoted source snippets): the app's
 * sans (Figtree, `font-sans`) at 16px with a roomier line height than the UI
 * chrome, so answers read as prose without changing voice mid-screen. The
 * serif voice is still one token away: swap `font-sans` for `font-voice`
 * (Source Serif 4, `--font-voice` in globals.css) and nothing else moves.
 */
export const ANSWER_TEXT_CLASS = "font-sans text-ax-text text-base leading-[1.7]";

const code = createCodePlugin({
  themes: ["github-light-high-contrast", "github-dark-high-contrast"]
});
const streamdownPlugins = {
  cjk,
  code,
  math: mathPlugin,
  renderers: [{ language: "mermaid", component: AnswerDiagram }]
};

// Streamdown closes an unfinished `$$` while text streams in; math stays as
// written until the model closes it, the same as in the web app.
const REMEND_OPTIONS = { katex: false };

/**
 * Assistant markdown (Streamdown) with Eneo defaults: GFM always on, accessible
 * tables/headings/lists/code regions (markdown-components.tsx) and Streamdown's
 * UI strings in the user's language. `remarkPlugins`, `rehypePlugins` and
 * `components` ADD to those defaults; memoize them in the caller so blocks are
 * not re-parsed on every render. Streamdown otherwise replaces its defaults:
 * dropping those loses GFM tables and the sanitize/harden pipeline.
 */
export const MessageResponse = memo(
  ({ className, remarkPlugins, rehypePlugins, components, ...props }: MessageResponseProps) => {
    const t = useTranslations();
    const translations = useStreamdownTranslations();
    const copyFeedback = useMemo(
      () => ({
        onCopy: () => toast.success(t("copied")),
        onError: () => toast.error(t("copy_failed"))
      }),
      [t]
    );
    const controls = useMemo(
      () => ({
        table: false,
        code: { copy: copyFeedback, download: true },
        mermaid: { copy: copyFeedback, download: true, fullscreen: true, panZoom: true }
      }),
      [copyFeedback]
    );
    const codeRegionLabel = useCallback(
      (language: string | null) =>
        language ? t("chat_md_code_label", { language }) : t("chat_md_code_label_plain"),
      [t]
    );
    const remark = useMemo(
      () => [...answerRemarkPlugins, ...(remarkPlugins ?? [])],
      [remarkPlugins]
    );
    const rehype = useMemo(
      () => [
        ...answerRehypePlugins,
        rehypeCodeBlockRegions(codeRegionLabel),
        ...(rehypePlugins ?? [])
      ],
      [rehypePlugins, codeRegionLabel]
    );
    const mergedComponents = useMemo(
      () => ({ ...markdownComponents, ...components }),
      [components]
    );

    return (
      <Streamdown
        className={cn(
          "eneo-answer size-full min-w-0 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
          className
        )}
        plugins={streamdownPlugins}
        controls={controls}
        remend={REMEND_OPTIONS}
        remarkPlugins={remark}
        rehypePlugins={rehype}
        components={mergedComponents}
        translations={translations}
        {...props}
      />
    );
  },
  (prevProps, nextProps) =>
    prevProps.children === nextProps.children &&
    prevProps.isAnimating === nextProps.isAnimating &&
    prevProps.remarkPlugins === nextProps.remarkPlugins &&
    prevProps.rehypePlugins === nextProps.rehypePlugins &&
    prevProps.components === nextProps.components &&
    prevProps.className === nextProps.className
);

MessageResponse.displayName = "MessageResponse";
