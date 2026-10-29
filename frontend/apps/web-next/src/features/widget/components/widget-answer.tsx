import { useTranslations } from "next-intl";
import { useMemo, type ComponentProps } from "react";
import { citationNumber, useCitationRemarkPlugins } from "@/components/ai-elements/citation";
import { MessageResponse } from "@/components/ai-elements/message";
import { trimPartialInref } from "@/lib/chat/inref";

const INREF_TAG = /<inref\s+id="([0-9a-fA-F]{8})"\s*(?:\/>|>\s*<\/inref>)/g;

/**
 * An answer's Markdown with its inline citations: each `<inref>` the
 * backend wrote becomes a small numbered marker that opens the sources list
 * below the message and jumps to the matching entry. Links open in a new
 * tab, since the answer sits in a 400 px frame on someone else's page.
 */
export function WidgetAnswer({
  answer,
  streaming,
  sourceCount,
  referenceIndex,
  prefix,
  revealSource
}: {
  answer: string;
  streaming: boolean;
  sourceCount: number;
  /** 0-based position of a cited id in the message's source list, or null. */
  referenceIndex: (citedId: string) => number | null;
  /** The message's own prefix for citation anchors. */
  prefix: string;
  revealSource: (index: number) => void;
}) {
  const t = useTranslations();
  const text = useMemo(() => {
    const visible = streaming ? trimPartialInref(answer) : answer;
    return visible.replace(INREF_TAG, (_tag, id: string) => {
      const index = referenceIndex(id.toLowerCase());
      return index === null ? "" : `${index + 1}`;
    });
  }, [answer, streaming, referenceIndex]);
  const remarkPlugins = useCitationRemarkPlugins(sourceCount, prefix);
  const components = useMemo(
    () => ({
      a: ({ href, children, title }: ComponentProps<"a">) => {
        const number = citationNumber(href, prefix, sourceCount);
        if (number !== null) {
          return (
            <a
              className="widget-citation"
              href={`#${prefix}-source-${number - 1}`}
              aria-label={t("widget_citation_label", { number })}
              onClick={(event) => {
                event.preventDefault();
                revealSource(number - 1);
              }}
            >
              {children}
            </a>
          );
        }
        return (
          <a
            href={href}
            title={title}
            target="_blank"
            rel="noopener noreferrer"
            className="text-ax-text-accent underline underline-offset-2"
          >
            {children}
          </a>
        );
      }
    }),
    [prefix, sourceCount, revealSource, t]
  );

  return (
    <MessageResponse
      className="widget-answer text-ax-text text-sm leading-normal"
      isAnimating={streaming}
      remarkPlugins={remarkPlugins}
      components={components}
    >
      {text}
    </MessageResponse>
  );
}
