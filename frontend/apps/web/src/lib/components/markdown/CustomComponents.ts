/**
 * We have some custom components in our markdown syntax.
 */
import type { Component } from "svelte";

/**
 * 1. EneoInfoBlob
 */

export type EneoInrefToken = {
  type: "eneoInref";
  level: "block" | "inline";
  raw: string;
  id: string;
};

export type EneoInrefCustomComponentProps = {
  /**
   * The generated token with the inref id and information about the tokens level (block or inline)
   */
  token: EneoInrefToken;
};

/**
 * Component that can be passed in to be rendered instead of the default component
 */
export type CustomInfoBlobComponent = Component<EneoInrefCustomComponentProps>;

/**
 * 2. EneoMention
 */
export type EneoMentionToken = {
  type: "eneoMention";
  level: "inline";
  raw: string;
  handle: string;
};

export type EneoMentionCustomComponentProps = {
  /**
   * The generated token with the mention content
   */
  token: EneoMentionToken;
};

export type CustomMentionComponent = Component<EneoMentionCustomComponentProps>;

export type EneoToken = EneoInrefToken | EneoMentionToken;
export type CustomRenderers = {
  inref?: CustomInfoBlobComponent;
  mention?: CustomMentionComponent;
};
