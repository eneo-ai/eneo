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

/**
 * 3. EneoFile: the name of a file of the conversation, where the text mentions it
 */
export type EneoFileToken = {
  type: "eneoFile";
  level: "inline";
  raw: string;
  name: string;
};

export type EneoFileCustomComponentProps = {
  /**
   * The generated token with the file's name as written in the text
   */
  token: EneoFileToken;
};

export type CustomFileComponent = Component<EneoFileCustomComponentProps>;

export type EneoToken = EneoInrefToken | EneoMentionToken | EneoFileToken;
export type CustomRenderers = {
  inref?: CustomInfoBlobComponent;
  mention?: CustomMentionComponent;
  file?: CustomFileComponent;
};
