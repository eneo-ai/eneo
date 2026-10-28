/**
 * LaTeX math for MessageResponse (Streamdown): `$…$`, `$$…$$`, `\(…\)`,
 * `\[…\]` and ```math fences, the same as the web app's marked lexer
 * (apps/web/src/lib/components/markdown/math.ts). remark-math owns `$$`; the
 * micromark constructs below add what models also write, `\(…\)`, `\[…\]`
 * and a single `$` that is not money. They run inside the Markdown parser, so
 * code, link destinations, lists and quotes stay the parser's. When a `$` is
 * money is decided by @eneo/markdown-math; both apps are tested against its
 * cases.json.
 */
import {
  canCloseDollar,
  canFollowWithDollar,
  canOpenDollar,
  katexOptions
} from "@eneo/markdown-math";
import type { Nodes, Paragraph, Parent, Root } from "mdast";
import { mathFromMarkdown, type InlineMath, type Math } from "mdast-util-math";
import { math } from "micromark-extension-math";
import { markdownLineEnding } from "micromark-util-character";
import type {
  Code,
  Construct,
  Effects,
  Extension,
  State,
  TokenizeContext
} from "micromark-util-types";
import rehypeKatex from "rehype-katex";
import type { MathPlugin } from "streamdown";
import type { Processor } from "unified";

// The token names remark-math's tokenizer declares; ours emit the same ones.
declare module "micromark-util-types" {
  interface TokenTypeMap {
    mathText: "mathText";
    mathTextData: "mathTextData";
    mathTextSequence: "mathTextSequence";
    llmMathFence: "llmMathFence";
  }
}

const BACKSLASH = 92;
const DOLLAR = 36;
const CLOSERS: Partial<Record<number, number>> = { 40: 41, 91: 93 }; // ( → ), [ → ]

/** A micromark code as the character the shared rules expect. */
function character(code: Code): string | undefined {
  if (code === null) return undefined;
  return code < 0 ? " " : String.fromCharCode(code); // negative codes are line endings and tabs
}

/**
 * `\(…\)` and `\[…\]`, up to the first unescaped closer, across lines. A
 * second opener of the same kind first means this one is text, so a run of
 * unclosed openers is read once rather than once per opener.
 */
function tokenizeBracketMath(this: TokenizeContext, effects: Effects, ok: State, nok: State) {
  let opener = 0;
  let closer = 0;
  let hasTex = false;
  const closing: Construct = { tokenize: tokenizeClosing, partial: true };
  return start;

  function start(code: Code) {
    effects.enter("mathText");
    effects.enter("mathTextSequence");
    effects.consume(code);
    return open;
  }

  function open(code: Code) {
    const expected = code === null ? undefined : CLOSERS[code];
    if (expected === undefined) return nok(code);
    opener = code!;
    closer = expected;
    effects.consume(code);
    effects.exit("mathTextSequence");
    return between;
  }

  function between(code: Code): State | undefined {
    if (code === null) return nok(code);
    if (markdownLineEnding(code)) {
      effects.enter("lineEnding");
      effects.consume(code);
      effects.exit("lineEnding");
      return between;
    }
    if (code === BACKSLASH) return effects.attempt(closing, done, escaped)(code);
    effects.enter("mathTextData");
    return data(code);
  }

  function data(code: Code): State | undefined {
    if (code === null || code === BACKSLASH || markdownLineEnding(code)) {
      effects.exit("mathTextData");
      return between(code);
    }
    if (code !== 32 && code !== -2) hasTex = true;
    effects.consume(code);
    return data;
  }

  // A backslash that does not close: it and the character it escapes are TeX.
  function escaped(code: Code) {
    hasTex = true;
    effects.enter("mathTextData");
    effects.consume(code);
    return escapedCharacter;
  }

  function escapedCharacter(code: Code) {
    if (code === opener) return nok(code);
    if (code === null || markdownLineEnding(code)) {
      effects.exit("mathTextData");
      return between(code);
    }
    effects.consume(code);
    effects.exit("mathTextData");
    return between;
  }

  function done(code: Code) {
    if (!hasTex) return nok(code);
    effects.exit("mathText");
    return ok(code);
  }

  function tokenizeClosing(effects: Effects, ok: State, nok: State) {
    return function backslash(code: Code) {
      effects.enter("mathTextSequence");
      effects.consume(code);
      return function close(code: Code) {
        if (code !== closer) return nok(code);
        effects.consume(code);
        effects.exit("mathTextSequence");
        return ok;
      };
    };
  }
}

/** `$…$` on one line; only the first unescaped `$` may close it. */
function tokenizeDollarMath(this: TokenizeContext, effects: Effects, ok: State, nok: State) {
  const before = character(this.previous);
  let last: string | undefined;
  return start;

  function start(code: Code) {
    effects.enter("mathText");
    effects.enter("mathTextSequence");
    effects.consume(code);
    return open;
  }

  function open(code: Code) {
    if (!canOpenDollar(before, character(code))) return nok(code);
    effects.exit("mathTextSequence");
    effects.enter("mathTextData");
    return data(code);
  }

  function data(code: Code): State | undefined {
    if (code === null || markdownLineEnding(code)) return nok(code);
    if (code === DOLLAR) {
      effects.exit("mathTextData");
      effects.enter("mathTextSequence");
      effects.consume(code);
      return close;
    }
    effects.consume(code);
    last = character(code);
    return code === BACKSLASH ? escapedCharacter : data;
  }

  function escapedCharacter(code: Code) {
    if (code === null || markdownLineEnding(code)) return nok(code);
    effects.consume(code);
    last = character(code);
    return data;
  }

  function close(code: Code) {
    if (!canCloseDollar(last, character(code))) return nok(code);
    effects.exit("mathTextSequence");
    effects.exit("mathText");
    return ok(code);
  }
}

// Emits remark-math's own token names, so mdast-util-math builds the nodes.
const llmMathSyntax: Extension = {
  text: {
    [BACKSLASH]: { name: "llmBracketMath", tokenize: tokenizeBracketMath },
    [DOLLAR]: {
      name: "llmDollarMath",
      tokenize: tokenizeDollarMath,
      // Without it every `$` would be a place to try math, remark-math's own
      // construct included, which must not start right after another `$`.
      previous: (code: Code) => canFollowWithDollar(character(code))
    }
  }
};

function isParent(node: Nodes): node is Nodes & Parent {
  return "children" in node;
}

function sourceOf(node: Nodes, source: string) {
  return source.slice(node.position?.start.offset ?? 0, node.position?.end.offset ?? 0);
}

// The shape remark-math gives a `$$` fence, which rehype-katex typesets as display.
function displayMath(value: string, from: Nodes): Math {
  return {
    type: "math",
    value,
    meta: null,
    position: from.position,
    data: {
      hName: "pre",
      hChildren: [
        {
          type: "element",
          tagName: "code",
          properties: { className: ["language-math", "math-display"] },
          children: [{ type: "text", value }]
        }
      ]
    }
  };
}

/**
 * A paragraph that holds nothing but a `$$…$$` or `\[…\]` formula becomes
 * display math; inside a sentence the same formula stays inline. The web app
 * applies the same rule to its tokens.
 */
function toDisplayMath(node: Nodes, source: string): Math | undefined {
  if (node.type !== "paragraph") return;
  const content = (node as Paragraph).children.filter(
    (child) => child.type !== "text" || child.value.trim()
  );
  const only = content.length === 1 ? content[0] : undefined;
  if (only?.type !== "inlineMath" || !(only as InlineMath).value.trim()) return;
  const raw = sourceOf(only, source);
  if (!raw.startsWith("$$") && !raw.startsWith("\\[")) return;
  return displayMath((only as InlineMath).value, node);
}

function isSpace(code: Code) {
  return code === 32 || code === -2 || code === -1; // space, tab, virtual space
}

/**
 * Looks ahead from a `$$` line for what makes it a fence in the web app too:
 * nothing else on the opening line, TeX inside, and a closing line of at
 * least as many `$`. Anything else stays a paragraph, so remark-math's text
 * math (`$$…$$` within the paragraph) or plain text reads it, never a fence
 * that runs to the end of the answer.
 */
function tokenizeClosedFence(this: TokenizeContext, effects: Effects, ok: State, nok: State) {
  // A lazy line has left the quote or list item the fence is in.
  const isLazyLine = () => Boolean(this.parser.lazy[this.now().line]);
  let open = 0;
  let close = 0;
  let indentSize = 0;
  let hasTex = false;
  let inLine = false;
  return openRun;

  // micromark consumes only inside an open token; one per line, closed before
  // each line ending.
  function take(code: Code) {
    if (!inLine) effects.enter("llmMathFence");
    inLine = true;
    effects.consume(code);
  }

  function endLine() {
    if (inLine) effects.exit("llmMathFence");
    inLine = false;
  }

  function openRun(code: Code): State | undefined {
    if (code === DOLLAR) {
      open++;
      take(code);
      return openRun;
    }
    return open < 2 ? nok(code) : openRest(code);
  }

  function openRest(code: Code): State | undefined {
    if (isSpace(code)) {
      take(code);
      return openRest;
    }
    return markdownLineEnding(code) ? lineEnding(code) : nok(code);
  }

  function lineEnding(code: Code) {
    endLine();
    effects.enter("lineEnding");
    effects.consume(code);
    effects.exit("lineEnding");
    return lineStart;
  }

  function lineStart(code: Code) {
    if (isLazyLine()) return nok(code);
    indentSize = 0;
    return indent(code);
  }

  // At most three columns before a closing fence, as remark-math allows (a
  // tab counts as the columns it expands to); further in, the line is TeX.
  function indent(code: Code): State | undefined {
    if (isSpace(code)) {
      if (++indentSize > 3) return content(code);
      take(code);
      return indent;
    }
    close = 0;
    return closeRun(code);
  }

  function closeRun(code: Code): State | undefined {
    if (code === DOLLAR) {
      close++;
      take(code);
      return closeRun;
    }
    return afterRun(code);
  }

  function afterRun(code: Code): State | undefined {
    if (isSpace(code)) {
      take(code);
      return afterRun;
    }
    if (close >= open && (code === null || markdownLineEnding(code))) {
      if (!hasTex) return nok(code);
      endLine();
      return ok(code);
    }
    if (close > 0) hasTex = true;
    return content(code);
  }

  function content(code: Code): State | undefined {
    if (code === null) return nok(code);
    if (markdownLineEnding(code)) return lineEnding(code);
    if (!isSpace(code)) hasTex = true;
    take(code);
    return content;
  }
}

const closedFence: Construct = { tokenize: tokenizeClosedFence, partial: true };

/** remark-math's flow math, entered only where {@link tokenizeClosedFence} agrees. */
function guardFence(fence: Construct): Construct {
  return {
    ...fence,
    tokenize(effects, ok, nok) {
      const start = (code: Code) => fence.tokenize.call(this, effects, ok, nok)(code);
      return effects.check(closedFence, start, nok);
    }
  };
}

function rewrite(parent: Parent, source: string) {
  for (let i = 0; i < parent.children.length; i++) {
    const node = parent.children[i]!;
    const display = toDisplayMath(node, source);
    if (display) parent.children[i] = display;
    else if (node.type === "inlineMath" && !node.value.trim()) {
      // `$$ $$` has no TeX; the web app shows it as written.
      parent.children[i] = { type: "text", value: sourceOf(node, source), position: node.position };
    } else if (isParent(node)) rewrite(node, source);
  }
}

/**
 * remark-math, put together from the same two packages, with its `$$` fence
 * guarded and our constructs added after its own, so they are tried first.
 */
function remarkLlmMath(this: Processor) {
  const syntax = math({ singleDollarTextMath: false });
  const fence = syntax.flow?.[DOLLAR];
  if (fence && !Array.isArray(fence)) syntax.flow = { [DOLLAR]: guardFence(fence) };
  const data = this.data();
  (data.micromarkExtensions ??= []).push(syntax, llmMathSyntax);
  (data.fromMarkdownExtensions ??= []).push(mathFromMarkdown());
  return (tree: Root, file: { value: unknown }) => rewrite(tree, String(file.value));
}

/**
 * Streamdown's math plugin, in its slot after the sanitizer. Replaces
 * `@streamdown/math` (remark-math with `$$` only) so both apps read the same
 * delimiters and typeset with the same KaTeX options.
 */
export const mathPlugin: MathPlugin = {
  name: "katex",
  type: "math",
  remarkPlugin: remarkLlmMath,
  rehypePlugin: [rehypeKatex, katexOptions(false)]
};
