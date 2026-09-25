"use client";

import { usePathname } from "next/navigation";
import { Cards } from "nextra/components";
import { useMDXComponents as getThemeComponents } from "nextra-theme-docs";
import type { ComponentProps } from "react";
import { localizeDocsHref, splitDocsPath } from "@/lib/languages";

const Anchor = getThemeComponents().a;

export function DocsLink(props: ComponentProps<"a">) {
  const { language } = splitDocsPath(usePathname());
  return (
    <Anchor {...props} href={localizeDocsHref(props.href || "", language)} />
  );
}

export function DocsCard(props: ComponentProps<typeof Cards.Card>) {
  const { language } = splitDocsPath(usePathname());
  return (
    <Cards.Card {...props} href={localizeDocsHref(props.href, language)} />
  );
}
