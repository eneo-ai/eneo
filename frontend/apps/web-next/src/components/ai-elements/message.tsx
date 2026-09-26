"use client";

import { cn } from "@/lib/utils";
import { cjk } from "@streamdown/cjk";
import { code } from "@streamdown/code";
import { math } from "@streamdown/math";
import { mermaid } from "@streamdown/mermaid";
import type { ComponentProps } from "react";
import { useTranslations } from "next-intl";
import { memo, useCallback, useMemo } from "react";
import { defaultRehypePlugins, defaultRemarkPlugins, Streamdown } from "streamdown";
import {
  markdownComponents,
  rehypeCodeBlockRegions,
  useStreamdownTranslations
} from "./markdown-components";

export type MessageResponseProps = ComponentProps<typeof Streamdown>;

const streamdownPlugins = { cjk, code, math, mermaid };

// Streamdown REPLACES its defaults when `remarkPlugins`/`rehypePlugins` are
// passed. The defaults carry GFM (tables, strikethrough, autolinks), code meta
// and the sanitize/harden pipeline, so dropping them rendered tables as raw
// `| a | b |` text. MessageResponse therefore always keeps them and appends the
// caller's plugins.
const DEFAULT_REMARK_PLUGINS = Object.values(defaultRemarkPlugins);
const DEFAULT_REHYPE_PLUGINS = Object.values(defaultRehypePlugins);

/**
 * Assistant markdown (Streamdown) with Eneo defaults: GFM always on, accessible
 * tables/headings/lists/code regions (markdown-components.tsx) and Streamdown's
 * UI strings in the user's language. `remarkPlugins`, `rehypePlugins` and
 * `components` ADD to those defaults; memoize them in the caller so blocks are
 * not re-parsed on every render.
 */
export const MessageResponse = memo(
  ({ className, remarkPlugins, rehypePlugins, components, ...props }: MessageResponseProps) => {
    const t = useTranslations();
    const translations = useStreamdownTranslations();
    const codeRegionLabel = useCallback(
      (language: string | null) =>
        language ? t("chat_md_code_label", { language }) : t("chat_md_code_label_plain"),
      [t]
    );
    const remark = useMemo(
      () => [...DEFAULT_REMARK_PLUGINS, ...(remarkPlugins ?? [])],
      [remarkPlugins]
    );
    const rehype = useMemo(
      () => [
        ...DEFAULT_REHYPE_PLUGINS,
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
        className={cn("size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0", className)}
        plugins={streamdownPlugins}
        controls={{ table: false }}
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
