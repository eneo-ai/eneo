import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Span } from "./passages";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    passageHighlight: {
      /** Marks `spans` in the document; none clears the mark. */
      highlightPassage: (spans: Span[]) => ReturnType;
    };
  }
}

export const passageHighlightKey = new PluginKey<DecorationSet>("passageHighlight");

/** The CSS class painted over a highlighted passage. */
export const PASSAGE_HIGHLIGHT_CLASS = "passage-highlight";

/**
 * Points out a passage (a quote the reader asked to see in place) as a
 * decoration, so neither the document nor the reader's selection changes.
 * The mark follows the text through later edits.
 */
export const PassageHighlight = Extension.create({
  name: "passageHighlight",

  addCommands() {
    return {
      highlightPassage:
        (spans) =>
        ({ tr, dispatch }) => {
          dispatch?.(tr.setMeta(passageHighlightKey, spans));
          return true;
        }
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: passageHighlightKey,
        state: {
          init: () => DecorationSet.empty,
          apply(tr, set) {
            const spans = tr.getMeta(passageHighlightKey) as Span[] | undefined;
            if (!spans) return set.map(tr.mapping, tr.doc);
            return DecorationSet.create(
              tr.doc,
              spans.map(({ from, to }) =>
                Decoration.inline(from, to, { class: PASSAGE_HIGHLIGHT_CLASS })
              )
            );
          }
        },
        props: {
          decorations: (state) => passageHighlightKey.getState(state)
        }
      })
    ];
  }
});
