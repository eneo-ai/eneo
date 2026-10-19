import type { Editor } from "@tiptap/core";
import { EditorState } from "@tiptap/pm/state";

/**
 * Puts `markdown` in the editor as the whole document, with nothing to undo.
 *
 * A streamed draft's frames, a version opening and a reset are not the
 * reader's doing: undo must not walk back through them, and nothing earlier
 * can be undone against a document that has been replaced under it. The
 * editor state is made anew with the same plugins, so no update is emitted;
 * decorations start empty and are placed again by whoever placed them.
 */
export function replaceContent(editor: Editor, markdown: string): void {
  const manager = editor.markdown;
  if (!manager) throw new Error("The editor has no Markdown extension");
  const doc = editor.schema.nodeFromJSON(manager.parse(markdown));
  editor.view.updateState(EditorState.create({ doc, plugins: editor.state.plugins }));
}
