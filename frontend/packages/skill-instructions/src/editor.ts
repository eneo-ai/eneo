import {
  Fragment,
  Schema,
  Slice,
  type Node as ProseMirrorNode,
} from "@tiptap/pm/model";
import {
  EditorState,
  NodeSelection,
  Plugin,
  TextSelection,
  type Transaction,
} from "@tiptap/pm/state";
import { EditorView } from "@tiptap/pm/view";
import { keymap } from "@tiptap/pm/keymap";
import { baseKeymap } from "@tiptap/pm/commands";
import { closeHistory, history, redo, undo } from "@tiptap/pm/history";
import {
  parseInstructionReferences,
  serializeReference,
  type InstructionReference,
  type InstructionTarget,
} from "./references";

export type ReferenceSelection = {
  documentVersion: number;
  from: number;
  to: number;
  reference?: InstructionReference;
};
type EditorOptions = {
  element: HTMLElement;
  value: string;
  id: string;
  label: string;
  placeholder?: string;
  describedBy?: string;
  disabled?: boolean;
  invalid?: boolean;
  editorClass: string;
  referenceClass: string;
  referenceTypeLabels?: Record<InstructionTarget["kind"], string>;
  onChange: (value: string) => void;
  onReference: (selection: ReferenceSelection | null) => void;
};

// The document is literal instruction text, not Markdown. Chat composer token
// placeholders and Markdown document editors cannot preserve this write contract.
const schema = new Schema({
  nodes: {
    doc: { content: "paragraph" },
    paragraph: {
      content: "(text|reference)*",
      whitespace: "pre",
      toDOM: () => ["p", 0],
    },
    text: { inline: true },
    reference: {
      inline: true,
      atom: true,
      selectable: true,
      attrs: { raw: {}, label: {}, kind: {} },
      toDOM: (node) => [
        "span",
        { "data-skill-reference": "", contenteditable: "false" },
        node.attrs.label,
      ],
      leafText: (node) => node.attrs.raw,
    },
  },
});

function sourceText(node: ProseMirrorNode): string {
  return node.textBetween(
    0,
    node.content.size,
    "",
    (leaf) => leaf.attrs.raw ?? "",
  );
}

function documentFor(value: string, source: boolean): ProseMirrorNode {
  let references: InstructionReference[] = [];
  if (!source) {
    try {
      references = parseInstructionReferences(value);
    } catch {
      /* Invalid source stays editable and is rejected by the save boundary. */
    }
  }
  const nodes: ProseMirrorNode[] = [];
  let cursor = 0;
  for (const reference of references) {
    if (cursor < reference.start)
      nodes.push(schema.text(value.slice(cursor, reference.start)));
    nodes.push(
      schema.nodes.reference.create({
        raw: reference.text,
        label: reference.label,
        kind: reference.target.kind,
      }),
    );
    cursor = reference.end;
  }
  if (cursor < value.length) nodes.push(schema.text(value.slice(cursor)));
  return schema.nodes.doc.create(
    null,
    schema.nodes.paragraph.create(null, nodes),
  );
}

function sourceOffset(doc: ProseMirrorNode, position: number): number {
  return doc.textBetween(
    1,
    Math.max(1, Math.min(position, doc.content.size - 1)),
    "",
    (leaf) => String(leaf.attrs.raw ?? ""),
  ).length;
}

function documentPosition(doc: ProseMirrorNode, offset: number): number {
  let remaining = offset;
  let result = 1;
  doc.firstChild!.forEach((node) => {
    if (remaining <= 0) return;
    const length = node.isText
      ? node.text!.length
      : String(node.attrs.raw).length;
    result += node.isText ? Math.min(remaining, length) : 1;
    remaining -= length;
  });
  return result;
}

function replaceDocument(
  state: EditorState,
  next: ProseMirrorNode,
): Transaction | null {
  const start = state.doc.content.findDiffStart(next.content);
  if (start === null) return null;
  const end = state.doc.content.findDiffEnd(next.content)!;
  const overlap = start - Math.min(end.a, end.b);
  return state.tr.replace(
    start,
    end.a + Math.max(0, overlap),
    next.slice(start, end.b + Math.max(0, overlap)),
  );
}

export function createInstructionEditor(options: EditorOptions) {
  let source = false;
  let documentVersion = 0;
  let disabled = options.disabled ?? false;
  let invalid = options.invalid ?? false;
  let view: EditorView;

  function selection(): ReferenceSelection {
    const { from, to } = view.state.selection;
    const value = sourceText(view.state.doc);
    const start = sourceOffset(view.state.doc, from);
    const end = sourceOffset(view.state.doc, to);
    let reference: InstructionReference | undefined;
    try {
      reference = parseInstructionReferences(value).find(
        (item) => item.start === start && item.end === end,
      );
    } catch {
      /* The source view lets the author repair malformed references. */
    }
    return { documentVersion, from: start, to: end, reference };
  }

  function normalise(state: EditorState) {
    const value = sourceText(state.doc);
    const next = documentFor(value, source);
    const change = replaceDocument(state, next);
    if (!change) return null;
    const from = documentPosition(
      next,
      sourceOffset(state.doc, state.selection.from),
    );
    const to = documentPosition(
      next,
      sourceOffset(state.doc, state.selection.to),
    );
    return change.setSelection(TextSelection.create(change.doc, from, to));
  }

  function openSelection() {
    if (disabled || view.composing) return false;
    options.onReference(selection());
    return true;
  }

  const state = EditorState.create({
    schema,
    doc: documentFor(options.value, source),
    plugins: [
      history(),
      keymap({
        "Mod-z": undo,
        "Mod-Shift-z": redo,
        "Mod-y": redo,
        "Mod-Enter": () => false,
        Enter: (current, dispatch) => {
          if (view.composing) return false;
          if (current.selection instanceof NodeSelection)
            return openSelection();
          dispatch?.(current.tr.insertText("\n").scrollIntoView());
          return true;
        },
        "Shift-Enter": (current, dispatch) => {
          dispatch?.(current.tr.insertText("\n"));
          return true;
        },
        Tab: () => false,
      }),
      keymap(baseKeymap),
      new Plugin({
        appendTransaction(transactions, _old, current) {
          if (
            view?.composing ||
            !transactions.some((transaction) => transaction.docChanged)
          )
            return null;
          return normalise(current);
        },
      }),
    ],
  });

  view = new EditorView(options.element, {
    state,
    editable: () => !disabled,
    attributes: () => ({
      id: options.id,
      role: "textbox",
      "aria-label": options.label,
      "aria-multiline": "true",
      "data-skill-instruction-editor": "",
      "aria-required": "true",
      "data-slot": "input-group-control",
      "data-empty": String(
        (view?.state ?? state).doc.firstChild?.childCount === 0,
      ),
      "data-placeholder": options.placeholder ?? "",
      "aria-placeholder": options.placeholder ?? "",
      "aria-describedby": options.describedBy ?? "",
      "aria-invalid": String(invalid),
      "aria-disabled": String(disabled),
      class: options.editorClass,
      spellcheck: "true",
    }),
    clipboardTextSerializer: (slice) =>
      sourceText(
        schema.nodes.paragraph.create(
          null,
          slice.content.firstChild?.isTextblock
            ? slice.content.firstChild.content
            : slice.content,
        ),
      ),
    clipboardTextParser: (text) =>
      text ? new Slice(Fragment.from(schema.text(text)), 0, 0) : Slice.empty,
    handlePaste: (_view, event) => {
      const text = event.clipboardData?.getData("text/plain");
      if (text === undefined || text === "") return true;
      view.dispatch(
        closeHistory(view.state.tr).insertText(text).scrollIntoView(),
      );
      return true;
    },
    handleDrop: (_view, event) => {
      // ProseMirror preserves the slice and owns moving versus copying internally.
      if (view.dragging) return false;
      // External HTML is never imported as editor nodes or fetched resources.
      const text = event.dataTransfer?.getData("text/plain");
      if (text) {
        const at = view.posAtCoords({
          left: event.clientX,
          top: event.clientY,
        });
        if (!at) return true;
        view.dispatch(
          closeHistory(view.state.tr).insertText(text, at.pos).scrollIntoView(),
        );
      }
      return true;
    },
    handleTextInput: (_view, from, to, text) => {
      if (text !== "@" || source || view.composing || disabled) return false;
      const value = sourceText(view.state.doc);
      const before = value.slice(0, sourceOffset(view.state.doc, from));
      const after = value.slice(sourceOffset(view.state.doc, to));
      if (before && !/[\s(]$/.test(before)) return false;
      // Ask the codec whether a reference here would be an active link. This
      // excludes examples and comments without a second syntax state machine.
      const probe = serializeReference("probe", {
        kind: "function",
        purpose: "web_search",
      });
      try {
        if (
          !parseInstructionReferences(before + probe + after).some(
            (item) => item.start === before.length,
          )
        )
          return false;
      } catch {
        return false;
      }
      view.dispatch(view.state.tr.insertText(text, from, to));
      options.onReference({
        documentVersion,
        from: before.length,
        to: before.length + 1,
      });
      return true;
    },
    handleDOMEvents: {
      compositionend: () => {
        // ProseMirror owns composition. Normalise on its next completed update.
        queueMicrotask(() => {
          if (!view.isDestroyed && !view.composing) {
            const change = normalise(view.state);
            if (change) view.dispatch(change);
          }
        });
        return false;
      },
    },
    nodeViews: {
      reference(node, _view, getPos) {
        const button = document.createElement("button");
        button.type = "button";
        button.tabIndex = -1;
        button.contentEditable = "false";
        button.className = options.referenceClass;
        button.dataset.skillReference = "";
        const typeLabel =
          options.referenceTypeLabels?.[
            node.attrs.kind as InstructionTarget["kind"]
          ];
        const fullName = typeLabel
          ? `${typeLabel}: ${node.attrs.label}`
          : node.attrs.label;
        button.title = fullName;
        button.setAttribute("aria-label", fullName);
        if (typeLabel) {
          const kind = document.createElement("span");
          kind.dataset.skillReferenceKind = "";
          kind.setAttribute("aria-hidden", "true");
          kind.textContent = `${typeLabel}:`;
          button.append(kind);
        }
        const label = document.createElement("span");
        label.dataset.skillReferenceLabel = "";
        label.setAttribute("aria-hidden", "true");
        label.textContent = node.attrs.label;
        button.append(label);
        button.addEventListener("click", () => {
          const pos = getPos();
          if (pos === undefined || disabled) return;
          view.dispatch(
            view.state.tr.setSelection(
              NodeSelection.create(view.state.doc, pos),
            ),
          );
          openSelection();
        });
        return { dom: button };
      },
    },
    dispatchTransaction(transaction) {
      const next = view.state.applyTransaction(transaction);
      view.updateState(next.state);
      if (next.transactions.some((item) => item.docChanged)) {
        // Inline pickers leave the editor reachable. An edit or external reset
        // invalidates their captured range before a delayed action can use it.
        documentVersion += 1;
        options.onReference(null);
        options.onChange(sourceText(next.state.doc));
      }
    },
  });

  return {
    getValue: () => sourceText(view.state.doc),
    getSelection: selection,
    focus: () => view.focus(),
    openReference: openSelection,
    setValue(value: string) {
      if (value === sourceText(view.state.doc)) return;
      const change = replaceDocument(view.state, documentFor(value, source));
      if (change) view.dispatch(closeHistory(change));
    },
    setState(next: { disabled: boolean; invalid: boolean }) {
      disabled = next.disabled;
      invalid = next.invalid;
      view.setProps({ editable: () => !disabled });
    },
    setSource(next: boolean) {
      source = next;
      const change = normalise(view.state);
      if (change) view.dispatch(change.setMeta("addToHistory", false));
      view.focus();
    },
    replace(
      selection: ReferenceSelection,
      label: string,
      target: InstructionTarget,
    ) {
      if (disabled || selection.documentVersion !== documentVersion)
        return false;
      const from = documentPosition(view.state.doc, selection.from);
      const to = documentPosition(view.state.doc, selection.to);
      view.dispatch(
        closeHistory(view.state.tr)
          .insertText(serializeReference(label, target), from, to)
          .scrollIntoView(),
      );
      view.focus();
      return true;
    },
    remove(selection: ReferenceSelection) {
      if (disabled || selection.documentVersion !== documentVersion)
        return false;
      view.dispatch(
        closeHistory(view.state.tr).delete(
          documentPosition(view.state.doc, selection.from),
          documentPosition(view.state.doc, selection.to),
        ),
      );
      view.focus();
      return true;
    },
    destroy: () => view.destroy(),
  };
}

export type InstructionEditor = ReturnType<typeof createInstructionEditor>;
