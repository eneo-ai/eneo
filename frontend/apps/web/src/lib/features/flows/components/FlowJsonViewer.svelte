<script lang="ts">
  type JsonTokenKind = "key" | "string" | "number" | "literal" | "punctuation" | "whitespace";

  type JsonToken = {
    offset: number;
    kind: JsonTokenKind;
    text: string;
  };

  let {
    value,
    maxHeightClass = "max-h-80",
    className = "",
    ariaLabel = "JSON"
  }: {
    value: unknown;
    maxHeightClass?: string;
    className?: string;
    ariaLabel?: string;
  } = $props();

  const source = $derived(formatJson(value));
  const tokens = $derived(tokenizeJson(source));

  function formatJson(payload: unknown): string {
    return JSON.stringify(payload, null, 2) ?? "null";
  }

  function tokenizeJson(json: string): JsonToken[] {
    const nextTokens: JsonToken[] = [];
    let index = 0;

    while (index < json.length) {
      const char = json[index];

      if (/\s/.test(char)) {
        const start = index;
        while (index < json.length && /\s/.test(json[index])) index += 1;
        nextTokens.push({ offset: start, kind: "whitespace", text: json.slice(start, index) });
        continue;
      }

      if ("{}[]:,".includes(char)) {
        nextTokens.push({ offset: index, kind: "punctuation", text: char });
        index += 1;
        continue;
      }

      if (char === '"') {
        const start = index;
        index += 1;
        while (index < json.length) {
          if (json[index] === "\\") {
            index += 2;
            continue;
          }
          if (json[index] === '"') {
            index += 1;
            break;
          }
          index += 1;
        }

        let lookahead = index;
        while (lookahead < json.length && /\s/.test(json[lookahead])) lookahead += 1;
        nextTokens.push({
          offset: start,
          kind: json[lookahead] === ":" ? "key" : "string",
          text: json.slice(start, index)
        });
        continue;
      }

      if (char === "-" || /\d/.test(char)) {
        const match = json.slice(index).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
        if (match) {
          nextTokens.push({ offset: index, kind: "number", text: match[0] });
          index += match[0].length;
          continue;
        }
      }

      const literal = ["true", "false", "null"].find((candidate) =>
        json.startsWith(candidate, index)
      );
      if (literal) {
        nextTokens.push({ offset: index, kind: "literal", text: literal });
        index += literal.length;
        continue;
      }

      nextTokens.push({ offset: index, kind: "string", text: char });
      index += 1;
    }

    return nextTokens;
  }

  function tokenClass(kind: JsonTokenKind): string {
    switch (kind) {
      case "key":
        return "text-accent-stronger";
      case "string":
        return "text-positive-stronger";
      case "number":
        return "text-warning-stronger";
      case "literal":
        return "text-negative-stronger";
      case "punctuation":
        return "text-muted";
      case "whitespace":
        return "";
    }
  }
</script>

<pre
  aria-label={ariaLabel}
  class="border-default bg-hover-dimmer mt-1 overflow-auto rounded-lg border p-3 font-mono text-[13px] leading-relaxed whitespace-pre-wrap break-words tabular-nums {maxHeightClass} {className}"><code
    >{#each tokens as token (token.offset)}<span class={tokenClass(token.kind)}>{token.text}</span
      >{/each}</code
  ></pre>
