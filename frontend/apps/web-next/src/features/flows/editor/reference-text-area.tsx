"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Token } from "@astryxdesign/core/Token";
import { useTranslations } from "use-intl";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState
} from "react";
import { cn } from "@/lib/utils";
import { VariablePicker } from "./editor-fields";
import {
  completeReference,
  referenceSuggestions,
  triggerAt,
  type ReferenceSuggestion,
  type ReferenceTrigger
} from "./reference-autocomplete";
import { previewParts, readTone, type PreviewPart, type ReadMeaning } from "./request-preview";
import { meaningLabel, readWarning, variableEntryLabel, variableGroupTitle } from "./step-labels";
import type { FlowPublic } from "./step-types";
import { insertToken, type VariableGroup } from "./step-variables";

/**
 * The flow and the place of the step whose texts are edited, so a reference
 * can be named for what it reads. The step editor provides it; without it a
 * text still completes references but shows no chips.
 */
export const TemplateScope = createContext<{
  flow: Pick<FlowPublic, "steps" | "metadata_json">;
  stepOrder: number;
} | null>(null);

/** The computed text metrics the chip layer copies from the text area, so both wrap alike. */
const MIRRORED = [
  "fontFamily",
  "fontSize",
  "fontWeight",
  "fontStyle",
  "fontVariant",
  "fontStretch",
  "letterSpacing",
  "wordSpacing",
  "lineHeight",
  "textIndent",
  "textTransform",
  "textAlign",
  "tabSize",
  "whiteSpace",
  "overflowWrap",
  "wordBreak",
  "direction",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft"
] as const;

function chipClass(meaning: ReadMeaning): string {
  const tone = readTone(meaning);
  if (tone === "missing") return "bg-ax-red-muted text-ax-red";
  if (tone === "warning") return "bg-ax-orange-muted text-ax-orange";
  return "bg-ax-blue-muted text-ax-blue";
}

/** The colour of a reference's token, by how it fares (`readTone`). */
export function tokenColor(meaning: ReadMeaning) {
  const tone = readTone(meaning);
  if (tone === "missing") return "red" as const;
  if (tone === "warning") return "orange" as const;
  return "blue" as const;
}

/** The text as the chip layer draws it, with a zero-width mark where the open trigger starts. */
function MirrorContent({ parts, mark }: { parts: PreviewPart[]; mark: number | null }) {
  const nodes: React.ReactNode[] = [];
  let at = 0;
  // A word joiner: no width and no new place to wrap, so the layer wraps as the text area does.
  const marker = (
    <span key="mark" data-reference-mark="">
      {"\u2060"}
    </span>
  );
  parts.forEach((part, index) => {
    const text = part.kind === "text" ? part.text : part.raw;
    if (mark !== null && mark >= at && mark < at + text.length) {
      if (part.kind === "text") {
        nodes.push(text.slice(0, mark - at), marker, text.slice(mark - at));
      } else {
        nodes.push(
          marker,
          <span key={index} className={cn("rounded-ax-inner", chipClass(part.meaning))}>
            {text}
          </span>
        );
      }
    } else if (part.kind === "text") {
      nodes.push(text);
    } else {
      nodes.push(
        <span key={index} className={cn("rounded-ax-inner", chipClass(part.meaning))}>
          {text}
        </span>
      );
    }
    at += text.length;
  });
  if (mark !== null && mark >= at) nodes.push(marker);
  return <>{nodes}</>;
}

/**
 * A text with references (an instruction, an underlag, an HTTP body), as the
 * reference editor's prompt editor (`FlowPromptEditor.svelte` in apps/web)
 * offers it: typing `{{` or `@` lists the references the step can read, and
 * each reference shows as a chip that says what it reads.
 *
 * Why our own and not an Astryx part: Astryx's TextArea stays the field (its
 * label, description, status and keyboard), but it has no completion, and
 * Typeahead and ChatComposerInput complete a single value or a chat draft
 * (Enter sends, history recall, tokens that do not come back from a stored
 * text). So the field is a combobox in the textbox form (WAI-ARIA APG): the
 * text area keeps focus and the keyboard (arrows, Enter or Tab, Escape),
 * `aria-activedescendant` names the highlighted suggestion and the count is
 * announced. The chips are drawn twice: in a layer over the text area that
 * copies its metrics (decorative, `aria-hidden`; hidden in forced colours,
 * where the text area's own text shows), and as a list under the field, so a
 * screen reader reads what each reference reads.
 */
export function TemplateTextArea({
  label,
  description,
  value,
  onChange,
  groups,
  rows = 6,
  status,
  placeholder,
  isRequired,
  isOptional,
  code = false
}: {
  label: string;
  description?: string;
  value: string;
  onChange: (value: string) => void;
  groups: VariableGroup[];
  rows?: number;
  status?: { type: "error" | "warning"; message?: string };
  placeholder?: string;
  isRequired?: boolean;
  isOptional?: boolean;
  code?: boolean;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const scope = useContext(TemplateScope);
  const listboxId = useId();
  const readsId = useId();
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const caretAfter = useRef<number | null>(null);
  const [trigger, setTrigger] = useState<ReferenceTrigger | null>(null);
  const [dismissed, setDismissed] = useState<number | null>(null);
  const [active, setActive] = useState(0);

  // The text's menus offer what it can read: the section's number only in
  // an instruction run once per section.
  const sectionIndex = groups.some((group) =>
    group.entries.some((entry) => entry.kind.type === "section_index")
  );
  const parts: PreviewPart[] = scope
    ? previewParts(value, scope.stepOrder, scope.flow, { sectionIndex })
    : [{ kind: "text", text: value }];
  const reads = [
    ...new Map(
      parts.flatMap((part) => (part.kind === "read" ? [[part.token, part] as const] : []))
    ).values()
  ];
  const warnings = scope
    ? [...new Set(reads.flatMap((read) => readWarning(read.meaning, scope.flow, t) ?? []))]
    : [];
  const suggestions = trigger
    ? referenceSuggestions(groups, trigger.query, (entry, group) =>
        group.type === "run"
          ? variableEntryLabel(entry, t)
          : t("flow_editor_tools_preview_read_step", {
              step: variableGroupTitle(group, t),
              what: variableEntryLabel(entry, t)
            })
      )
    : [];
  const open = trigger !== null && suggestions.length > 0;
  const activeIndex = Math.min(active, Math.max(suggestions.length - 1, 0));
  const optionId = (index: number) => `${listboxId}-${index}`;

  // The chip layer follows the text area's box and metrics, and the list
  // opens under the trigger: written to the DOM, as both are layout.
  useLayoutEffect(() => {
    const area = areaRef.current;
    const box = boxRef.current;
    const mirror = mirrorRef.current;
    if (!area || !box || !mirror) return;
    function place() {
      if (!area || !box || !mirror) return;
      const style = getComputedStyle(area);
      const areaRect = area.getBoundingClientRect();
      const boxRect = box.getBoundingClientRect();
      for (const property of MIRRORED) mirror.style[property] = style[property];
      mirror.style.top = `${areaRect.top - boxRect.top + area.clientTop}px`;
      mirror.style.left = `${areaRect.left - boxRect.left + area.clientLeft}px`;
      mirror.style.width = `${area.clientWidth}px`;
      mirror.style.height = `${area.clientHeight}px`;
      mirror.scrollTop = area.scrollTop;
      const list = listRef.current;
      if (!list) return;
      const mark = mirror.querySelector("[data-reference-mark]")?.getBoundingClientRect();
      const visible = mark && mark.height > 0;
      const top = visible ? mark.bottom - boxRect.top : areaRect.bottom - boxRect.top;
      const left = visible ? mark.left - boxRect.left : 0;
      list.style.top = `${top + 4}px`;
      list.style.left = `${Math.max(0, Math.min(left, boxRect.width - list.offsetWidth))}px`;
    }
    place();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(place);
    observer.observe(area);
    return () => observer.disconnect();
  });

  // A chosen reference puts the caret after it once the new text is in the field.
  useLayoutEffect(() => {
    const caret = caretAfter.current;
    const area = areaRef.current;
    if (caret === null || !area) return;
    caretAfter.current = null;
    area.focus();
    area.setSelectionRange(caret, caret);
  }, [value]);

  useEffect(() => {
    if (open)
      announce(t("flow_step_editor_reference_suggestions_count", { count: suggestions.length }));
  }, [announce, open, suggestions.length, t]);

  useEffect(() => {
    if (open)
      document.getElementById(optionId(activeIndex))?.scrollIntoView?.({ block: "nearest" });
  });

  /** Opens, follows or closes the list for where the caret is now. */
  function follow(typed: boolean) {
    const area = areaRef.current;
    if (!area || area.selectionStart !== area.selectionEnd) {
      setTrigger(null);
      return;
    }
    const next = triggerAt(area.value, area.selectionStart, {
      typed,
      wasAt: trigger?.kind === "at"
    });
    if (next && !typed && next.start === dismissed) {
      setTrigger(null);
      return;
    }
    if (typed) setDismissed(null);
    if (next?.start !== trigger?.start) setActive(0);
    setTrigger(next);
  }

  function choose(suggestion: ReferenceSuggestion) {
    const area = areaRef.current;
    if (!area || !trigger) return;
    const next = completeReference(area.value, trigger, area.selectionStart, suggestion.token);
    caretAfter.current = next.caret;
    setTrigger(null);
    onChange(next.text);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!open || event.nativeEvent.isComposing) return;
    const count = suggestions.length;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setActive((activeIndex + (event.key === "ArrowDown" ? 1 : count - 1)) % count);
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      choose(suggestions[activeIndex]!);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setDismissed(trigger?.start ?? null);
      setTrigger(null);
    }
  }

  function insert(token: string) {
    const area = areaRef.current;
    const selection = area ? { start: area.selectionStart, end: area.selectionEnd } : null;
    const next = insertToken(value, token, selection);
    // The menu hands focus back to its trigger as it closes; then the text
    // takes it, with the caret after the inserted reference.
    requestAnimationFrame(() => {
      caretAfter.current = next.caret;
      onChange(next.text);
    });
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={boxRef}
        className={cn(
          "relative",
          // Over the chips the text area's own text gives way; its caret and selection stay.
          reads.length > 0 && "[&_textarea]:caret-ax-text [&_textarea]:text-transparent"
        )}
      >
        <TextArea
          ref={areaRef}
          label={label}
          description={[
            description,
            t("flow_step_editor_reference_hint", { braces: "{{", at: "@" })
          ]
            .filter(Boolean)
            .join(" ")}
          value={value}
          onChange={(next, event) => {
            onChange(next);
            const inputType = (event.nativeEvent as InputEvent).inputType ?? "";
            if (inputType.startsWith("delete")) setTrigger(null);
            else follow(inputType === "insertText");
          }}
          onKeyDown={onKeyDown}
          onKeyUp={(event) => {
            if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) follow(false);
          }}
          onClick={() => follow(false)}
          onBlur={() => setTrigger(null)}
          onScroll={() => {
            if (mirrorRef.current && areaRef.current) {
              mirrorRef.current.scrollTop = areaRef.current.scrollTop;
            }
          }}
          aria-autocomplete="list"
          aria-controls={open ? listboxId : undefined}
          aria-activedescendant={open ? optionId(activeIndex) : undefined}
          rows={rows}
          status={
            status ??
            (warnings.length > 0 ? { type: "warning", message: warnings.join(" ") } : undefined)
          }
          placeholder={placeholder}
          isRequired={isRequired}
          isOptional={isOptional}
          hasSpellCheck={!code}
          width="100%"
        />
        <div
          ref={mirrorRef}
          aria-hidden="true"
          className={cn(
            "text-ax-text pointer-events-none absolute top-0 left-0 overflow-hidden forced-colors:hidden",
            reads.length === 0 && "invisible"
          )}
        >
          <MirrorContent parts={parts} mark={open && trigger ? trigger.start : null} />
          {/* A text that ends in a line break gets its last, empty line too. */}
          {"\u200b"}
        </div>
        {open ? (
          <div
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label={t("flow_step_editor_reference_suggestions")}
            className="bg-ax-popover border-ax-border rounded-ax-container shadow-ax-med absolute z-20 flex max-h-60 w-80 max-w-full flex-col overflow-y-auto border p-1"
          >
            {suggestions.map((suggestion, index) => (
              <div
                key={suggestion.token}
                id={optionId(index)}
                role="option"
                aria-selected={index === activeIndex}
                tabIndex={-1}
                // The text area keeps focus; the choice is made on release.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(suggestion)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") choose(suggestion);
                }}
                className={cn(
                  "rounded-ax-inner flex cursor-pointer flex-col px-2 py-1.5",
                  index === activeIndex ? "bg-ax-selected" : "hover:bg-ax-hover"
                )}
              >
                <Text size="sm">{suggestion.label}</Text>
                <Text type="supporting" size="sm" className="font-mono break-all">
                  {`{{${suggestion.token}}}`}
                </Text>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      {scope && reads.length > 0 ? (
        <div className="flex flex-col gap-1">
          <Text type="supporting" size="sm" id={readsId}>
            {t("flow_step_editor_reads_heading")}
          </Text>
          <ul aria-labelledby={readsId} className="m-0 flex list-none flex-wrap gap-1 p-0">
            {reads.map((read) => (
              <li key={read.token}>
                <Token
                  size="sm"
                  color={tokenColor(read.meaning)}
                  label={meaningLabel(read.meaning, read.token, scope.flow, t)}
                  description={`{{${read.token}}}`}
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div>
        <VariablePicker groups={groups} onInsert={insert} />
      </div>
    </div>
  );
}
