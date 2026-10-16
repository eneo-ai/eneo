import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import plaintext from "highlight.js/lib/languages/plaintext";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { createLowlight } from "lowlight";

// The languages a document's code is highlighted in; an untagged block is
// detected among them.
const lowlight = createLowlight({
  javascript,
  python,
  c,
  xml,
  json,
  bash,
  yaml,
  sql,
  plaintext
});

/**
 * A fenced code block, highlighted with `hljs-*` classes that globals.css
 * colours from the theme's categorical text tokens. The fence's language tag
 * is kept in the document.
 */
export const DocumentCodeBlock = CodeBlockLowlight.configure({
  lowlight,
  HTMLAttributes: { class: "document-code" }
});
