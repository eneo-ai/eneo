import { getSchema } from "@tiptap/core";
import { ChangeSet, simplifyChanges } from "@tiptap/pm/changeset";
import type { Node } from "@tiptap/pm/model";
import { StepMap } from "@tiptap/pm/transform";
import { documentExtensions, documentMarkdown } from "./extensions";

/** What a version changed against the one before it, in the current document's positions. */
export type Change =
  | { kind: "added"; from: number; to: number }
  /** Text the earlier version had here and this one has not. */
  | { kind: "removed"; at: number; text: string };

/**
 * The differences between two documents, placed in `current`: added text as
 * the stretches it occupies, removed text at the position where it stood.
 *
 * ProseMirror's changeset finds them: given one step that replaces the whole
 * of `previous` with `current`, it works out the smallest set of changes
 * between the two, which is then widened to whole words.
 */
export function documentChanges(previous: Node, current: Node): Change[] {
  const whole = new StepMap([0, previous.content.size, current.content.size]);
  const set = ChangeSet.create(previous).addSteps(current, [whole], null);
  return simplifyChanges(set.changes, current).flatMap((change) => {
    const found: Change[] = [];
    if (change.fromB < change.toB)
      found.push({ kind: "added", from: change.fromB, to: change.toB });
    const removed = previous.textBetween(change.fromA, change.toA, " ").trim();
    if (removed) found.push({ kind: "removed", at: change.fromB, text: removed });
    return found;
  });
}

// One parser for every comparison: it builds the same document the editor
// shows, so the positions it finds are the editor's.
let parser: { parse: (markdown: string) => Node } | undefined;
function parse(markdown: string): Node {
  if (!parser) {
    const schema = getSchema(documentExtensions());
    const manager = documentMarkdown();
    parser = { parse: (source) => schema.nodeFromJSON(manager.parse(source)) };
  }
  return parser.parse(markdown);
}

/** What `current` changed against `previous`, both as Markdown. */
export function changesBetween(previous: string, current: string): Change[] {
  return documentChanges(parse(previous), parse(current));
}
