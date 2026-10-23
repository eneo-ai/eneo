"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { createMermaidPlugin } from "@streamdown/mermaid";
import { Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useContext, useMemo, useState } from "react";
import { CodeBlock, Streamdown, StreamdownContext, type CustomRendererProps } from "streamdown";
import { useStreamdownTranslations } from "./markdown-components";

/**
 * Streamdown owns diagrams, zoom, copy and download. Astryx owns the modal:
 * Streamdown 2.7's fullscreen overlay neither moves nor contains focus.
 * The nested renderer has no custom renderers, so it cannot recurse here.
 */
export function AnswerDiagram({ code, isIncomplete }: CustomRendererProps) {
  const t = useTranslations();
  const translations = useStreamdownTranslations();
  const { controls, isAnimating, mermaid } = useContext(StreamdownContext);
  const { resolvedTheme } = useTheme();
  // Streamdown's memo compares plugins, but not its mermaid prop. Keep the
  // theme here so already rendered diagrams update without remounting answers.
  const { options, plugins } = useMemo(
    () => ({
      options: {
        ...mermaid,
        config: { theme: resolvedTheme === "dark" ? "dark" : "neutral", ...mermaid?.config }
      },
      plugins: { mermaid: createMermaidPlugin() }
    }),
    [mermaid, resolvedTheme]
  );
  const [open, setOpen] = useState(false);
  const diagramControls = typeof controls === "boolean" ? controls : controls.mermaid;
  const canExpand =
    diagramControls !== false &&
    (typeof diagramControls !== "object" || diagramControls.fullscreen !== false);
  const nestedControls = useMemo(
    () => ({
      mermaid:
        diagramControls === false
          ? false
          : { ...(typeof diagramControls === "object" ? diagramControls : {}), fullscreen: false }
    }),
    [diagramControls]
  );
  // Use a longer fence than anything in a label: diagram source stays code.
  const markdown = useMemo(() => {
    const longest = (code.match(/`+/g) ?? []).reduce(
      (length, run) => Math.max(length, run.length),
      2
    );
    const fence = "`".repeat(longest + 1);
    return `${fence}mermaid\n${code}\n${fence}`;
  }, [code]);

  if (isIncomplete) return <CodeBlock code={code} language="mermaid" isIncomplete />;

  const preview = (
    <Streamdown
      className="eneo-answer"
      mode="static"
      parseIncompleteMarkdown={false}
      plugins={plugins}
      mermaid={options}
      controls={nestedControls}
      translations={translations}
      isAnimating={isAnimating}
    >
      {markdown}
    </Streamdown>
  );

  return (
    <>
      {preview}
      {canExpand && (
        <div className="flex justify-end">
          <Button
            label={t("chat_md_fullscreen")}
            icon={<Maximize2 aria-hidden="true" />}
            variant="ghost"
            size="sm"
            isDisabled={isAnimating}
            onClick={() => setOpen(true)}
          />
        </div>
      )}
      <Dialog isOpen={open} onOpenChange={setOpen} variant="fullscreen">
        <Layout
          header={<DialogHeader title={t("chat_md_diagram_label")} onOpenChange={setOpen} />}
          content={<LayoutContent>{preview}</LayoutContent>}
        />
      </Dialog>
    </>
  );
}
