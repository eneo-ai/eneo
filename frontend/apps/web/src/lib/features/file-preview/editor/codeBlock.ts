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

// The languages the chat's code block knows (see $lib/components/CodeBlock.svelte),
// so a document's code looks the same as code in an answer.
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
 * A fenced code block, highlighted with the `hljs-*` classes the chat's code
 * block paints (its colour theme is global). The fence's language tag is kept
 * in the document; an untagged block is detected among the known languages.
 */
export const DocumentCodeBlock = CodeBlockLowlight.configure({
  lowlight,
  HTMLAttributes: { class: "bg-overlay-stronger rounded-lg px-8 py-7 overflow-auto" }
});
