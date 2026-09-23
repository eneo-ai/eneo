import type { MarkedToken } from "marked";
import type { Component, Snippet } from "svelte";
import type { EneoToken } from "../CustomComponents";
import Heading from "./Heading.svelte";
import Text from "./Text.svelte";
import Paragraph from "./Paragraph.svelte";
import List from "./List.svelte";
import ListItem from "./ListItem.svelte";
import Strong from "./Strong.svelte";
import Emphasis from "./Emphasis.svelte";
import Code from "./Code.svelte";
import Inref from "./Inref.svelte";
import Mention from "./Mention.svelte";
import CodeSpan from "./CodeSpan.svelte";
import Blockquote from "./Blockquote.svelte";
import Del from "./Del.svelte";
import Br from "./Br.svelte";
import Hr from "./Hr.svelte";
import Space from "./Space.svelte";
import Def from "./Def.svelte";
import Table from "./Table.svelte";
import Link from "./Link.svelte";
import Image from "./Image.svelte";
import Html from "./Html.svelte";

type TokenMap = {
  [K in MarkedToken["type"]]: Extract<MarkedToken, { type: K }>;
} & {
  [K in EneoToken["type"]]: Extract<EneoToken, { type: K }>;
};

export type SupportedToken = TokenMap[keyof TokenMap];

export type Renderers = {
  [K in keyof TokenMap]:
    | Component<{
        token: TokenMap[K];
        children?: Snippet;
      }>
    | Component;
};

export const renderers: Renderers = {
  // Custom blocks
  eneoInref: Inref,
  eneoMention: Mention,
  // Basic markdown blocks
  heading: Heading,
  text: Text,
  paragraph: Paragraph,
  list: List,
  list_item: ListItem,
  strong: Strong,
  em: Emphasis,
  code: Code,
  codespan: CodeSpan,
  blockquote: Blockquote,
  del: Del,
  br: Br,
  hr: Hr,
  space: Space,
  def: Def,
  escape: Space,
  table: Table,
  link: Link,
  image: Image,
  html: Html // We're not rendering any html tags
};

export function isSupportedToken(token: { type: string }): token is SupportedToken {
  return token.type in renderers;
}

export function hasChildTokens<T extends SupportedToken>(
  token: T
): token is T & { tokens: SupportedToken[] } {
  return "tokens" in token && token.tokens !== undefined && token.tokens.length > 0;
}
