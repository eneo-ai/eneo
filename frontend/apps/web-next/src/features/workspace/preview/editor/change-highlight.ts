import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Change } from "./changes";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    changeHighlight: {
      /** Shows `changes` in the document; none clears them. */
      showChanges: (changes: Change[]) => ReturnType;
    };
  }
}

export const changeHighlightKey = new PluginKey<DecorationSet>("changeHighlight");

/** The classes painted over added text and at removed text. */
export const CHANGE_ADDED_CLASS = "change-added";
export const CHANGE_REMOVED_CLASS = "change-removed";

const removed = (text: string) => () => {
  const mark = document.createElement("del");
  mark.className = CHANGE_REMOVED_CLASS;
  mark.textContent = text;
  mark.setAttribute("contenteditable", "false");
  return mark;
};

/**
 * Shows what a version changed against the one before it: added words as a
 * mark over the text, removed words struck through where they stood. These
 * are decorations, so the document is untouched and they follow the text
 * through the reader's edits.
 */
export const ChangeHighlight = Extension.create({
  name: "changeHighlight",

  addCommands() {
    return {
      showChanges:
        (changes) =>
        ({ tr, dispatch }) => {
          dispatch?.(tr.setMeta(changeHighlightKey, changes));
          return true;
        }
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: changeHighlightKey,
        state: {
          init: () => DecorationSet.empty,
          apply(tr, set) {
            const changes = tr.getMeta(changeHighlightKey) as Change[] | undefined;
            if (!changes) return set.map(tr.mapping, tr.doc);
            return DecorationSet.create(
              tr.doc,
              changes.map((change) =>
                change.kind === "added"
                  ? Decoration.inline(change.from, change.to, { class: CHANGE_ADDED_CLASS })
                  : Decoration.widget(change.at, removed(change.text), { side: -1 })
              )
            );
          }
        },
        props: {
          decorations: (state) => changeHighlightKey.getState(state)
        }
      })
    ];
  }
});
