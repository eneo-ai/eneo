/// <reference lib="dom" />
import { useMemo, useState, type ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { copyText } from "./clipboard";
import { highlight, type CodeLanguage } from "./highlight";

type CodeProps = {
  /** The text shown, as it is; it is never interpreted. */
  text: string;
  /** Highlighted as this language; without one the text is shown plain, as logs are. */
  language?: CodeLanguage;
  /** Names the block in its header; without one the block has no header. */
  label?: string;
  /** Said after the label in the header, for what the reader may want to know about the text. */
  meta?: ReactNode;
  /** Numbered lines, for text the reader may need to refer into. */
  lineNumbers?: boolean;
  /** The copy button's labels; without them the block has no copy button. */
  copy?: { label: string; copied: string };
};

/**
 * A block of code or other monospaced text: a header with its name and a copy button, then the
 * text in a scrolling, bordered area with highlighting from the theme's colours. Long lines
 * scroll sideways rather than wrap, so the text keeps the shape it was written in.
 */
export function Code({ text, language, label, meta, lineNumbers, copy }: CodeProps) {
  const [copied, setCopied] = useState(false);
  const html = useMemo(() => highlight(text, language), [text, language]);
  const lines = useMemo(() => (lineNumbers ? text.split("\n").length : 0), [text, lineNumbers]);

  const onCopy = async () => {
    await copyText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="eneo-code-block">
      {(label || copy) && (
        <div className="eneo-code-header">
          <div className="eneo-code-title">
            {label && (
              <Text type="supporting" weight="medium">
                {label}
              </Text>
            )}
            {meta && (
              <Text type="supporting" color="secondary">
                {meta}
              </Text>
            )}
          </div>
          {copy && (
            <Button
              variant="ghost"
              size="sm"
              label={copied ? copy.copied : copy.label}
              icon={<Icon icon={copied ? "check" : "copy"} />}
              onClick={() => void onCopy()}
            />
          )}
        </div>
      )}
      <pre className="eneo-code" data-language={language}>
        {lines > 0 && (
          <span className="eneo-code-lines" aria-hidden="true">
            {Array.from({ length: lines }, (_, index) => index + 1).join("\n")}
          </span>
        )}
        <code className="hljs" dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  );
}
