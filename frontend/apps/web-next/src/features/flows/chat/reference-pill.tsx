"use client";

import { Button } from "@astryxdesign/core/Button";
import { Popover } from "@astryxdesign/core/Popover";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { CircleAlert, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
  type RefObject
} from "react";
import type { ComposerInsert } from "@/features/chat/chat-references";
import { cn } from "@/lib/utils";
import { meaningLabel, readWarning } from "../editor/step-labels";
import type { FlowPublic } from "../editor/step-types";
import { stepLabel } from "../flow-labels";
import { referenceStep, referenceTone, valueWhat, type Reference } from "./references";

type Translate = ReturnType<typeof useTranslations>;
type Flow = Pick<FlowPublic, "steps" | "metadata_json">;

type Card = { reference: Reference; anchor: HTMLElement };

/** The flow a chat is about, how to show one of its steps, and the one open reference card. */
type FlowReferencesValue = {
  flow: Flow;
  /** Brings the step's card into view; false when the card is not on the page. */
  onShowStep: (stepId: string) => boolean;
  /** The chat's composer, to put a reference into; null while there is none. */
  composer: ComposerInsert | null;
  card: Card | null;
  openCard: (reference: Reference, anchor: HTMLElement) => void;
};

const FlowReferencesContext = createContext<FlowReferencesValue | null>(null);

export function useFlowReferences(): FlowReferencesValue | null {
  return useContext(FlowReferencesContext);
}

/** What a pill says: "1 Extrahera" for a step, "1 Extrahera › fastighet" for a value. */
export function referenceLabel(reference: Reference, flow: Flow, t: Translate): string {
  const step = referenceStep(reference, flow);
  const stepText = step
    ? `${step.step_order} ${step.user_description?.trim() || t("flows_step_unnamed")}`
    : null;
  if (reference.kind === "step") return stepText ?? reference.name;
  const what = valueWhat(reference.meaning);
  const whatText =
    what === null
      ? null
      : what.type === "field"
        ? what.field
        : what.type === "text"
          ? t("flows_chat_reference_value_text")
          : t("flows_chat_reference_value_structured");
  if (stepText && whatText) return `${stepText} › ${whatText}`;
  return meaningLabel(reference.meaning, reference.token, flow, t);
}

/** What the reference is: the step, or what a value is of which step ("Fältet fastighet · Steg 1: Extrahera"). */
export function referenceDescription(reference: Reference, flow: Flow, t: Translate): string {
  const step = referenceStep(reference, flow);
  const stepText = step ? stepLabel(step, t) : null;
  // A removed step: the note below says so.
  if (reference.kind === "step") return stepText ?? t("flows_chat_reference_item_step");
  const what = valueWhat(reference.meaning);
  const whatText =
    what === null
      ? meaningLabel(reference.meaning, reference.token, flow, t)
      : what.type === "field"
        ? t("flow_step_editor_variable_step_field", { field: what.field })
        : what.type === "text"
          ? t("flows_chat_reference_item_text")
          : t("flows_chat_reference_item_structured");
  return stepText && what !== null ? `${whatText} · ${stepText}` : whatText;
}

/** What is wrong with a reference, or null: its step is gone, or it reads nothing useful. */
export function referenceNote(reference: Reference, flow: Flow, t: Translate): string | null {
  if (reference.kind === "step") {
    return reference.step ? null : t("flows_chat_reference_step_missing");
  }
  if (reference.meaning.kind === "missing") {
    return meaningLabel(reference.meaning, reference.token, flow, t);
  }
  return readWarning(reference.meaning, flow, t);
}

/**
 * A reference as a pill: grey for a step, blue for a value; orange with a
 * warning icon when it reads nothing useful, red with an alert icon when its
 * step is gone (the icon says it, not the colour alone).
 */
export function ReferencePill({
  reference,
  className
}: {
  reference: Reference;
  className?: string;
}) {
  const t = useTranslations();
  const refs = useFlowReferences();
  if (!refs) return <span className={className}>{reference.raw}</span>;
  const tone = referenceTone(reference);
  const color =
    tone === "missing"
      ? "red"
      : tone === "warning"
        ? "orange"
        : reference.kind === "step"
          ? "gray"
          : "blue";
  const icon =
    tone === "missing" ? (
      <CircleAlert aria-hidden="true" />
    ) : tone === "warning" ? (
      <TriangleAlert aria-hidden="true" />
    ) : undefined;
  return (
    <Token
      size="sm"
      color={color}
      icon={icon}
      label={referenceLabel(reference, refs.flow, t)}
      className={cn("align-baseline", className)}
    />
  );
}

/**
 * A pill in a message: a button that opens the reference card. The card is
 * one popover for the whole chat (see FlowReferences), anchored to the pill
 * that was pressed, so a pill in an answer's paragraph holds nothing but
 * the button.
 */
export function ReferencePillButton({ reference }: { reference: Reference }) {
  const refs = useFlowReferences();
  const [element, setElement] = useState<HTMLButtonElement | null>(null);
  if (!refs) return <>{reference.raw}</>;
  const open = refs.card?.anchor === element && element !== null;
  return (
    <button
      ref={setElement}
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={(event) => refs.openCard(reference, event.currentTarget)}
      className="focus-visible:outline-ring rounded-ax-inner inline-flex align-baseline focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <ReferencePill reference={reference} />
    </button>
  );
}

/** The card a pill opens: the reference as written, what is wrong with it, and its actions. */
function ReferenceCard({
  card,
  onClose
}: {
  card: Card | null;
  /** Closes the card; focus returns to the pill unless `refocus` is false. */
  onClose: (options?: { refocus: boolean }) => void;
}) {
  const t = useTranslations();
  const refs = useFlowReferences()!;
  // The anchor as a ref object the popover can read; a pill is never a React ref.
  const anchorRef = useMemo(() => ({ current: card?.anchor }) as RefObject<HTMLElement>, [card]);
  const reference = card?.reference;
  const step = reference ? referenceStep(reference, refs.flow) : null;
  const tone = reference ? referenceTone(reference) : "reads";
  const note = reference ? referenceNote(reference, refs.flow, t) : null;
  return (
    <Popover
      anchorRef={anchorRef}
      isOpen={card !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      placement="above"
      label={t("flows_chat_reference_card")}
      closeButtonLabel={t("close")}
      width={300}
      content={
        reference ? (
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-0.5">
              <Text type="label" weight="semibold" as="p" display="block" className="m-0">
                {referenceLabel(reference, refs.flow, t)}
              </Text>
              <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                {referenceDescription(reference, refs.flow, t)}
              </Text>
            </div>
            {/* As it is written in a message, for anyone who types references. */}
            <Text
              type="code"
              size="xsm"
              as="p"
              display="block"
              className="text-ax-text-secondary m-0 break-all"
            >
              {reference.raw}
            </Text>
            {note ? (
              <p
                className={cn(
                  "m-0 flex items-start gap-1.5 text-sm",
                  tone === "missing" ? "text-ax-error" : "text-ax-warning"
                )}
              >
                {tone === "missing" ? (
                  <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                ) : (
                  <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                )}
                <span>{note}</span>
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {refs.composer ? (
                <Button
                  size="sm"
                  label={t("flows_chat_reference_insert")}
                  onClick={() => {
                    // The pill goes to the caret and focus with it.
                    refs.composer?.insertToken({
                      value: reference.raw,
                      render: () => <ReferencePill reference={reference} />
                    });
                    onClose({ refocus: false });
                  }}
                />
              ) : null}
              {step?.id ? (
                <Button
                  size="sm"
                  variant={refs.composer ? "ghost" : undefined}
                  label={t("flows_chat_reference_show_step")}
                  onClick={() => {
                    refs.onShowStep(step.id!);
                    onClose();
                  }}
                />
              ) : null}
            </div>
          </div>
        ) : null
      }
    />
  );
}

/**
 * Gives a chat its flow's references: the pills read the flow here, and the
 * one reference card opens from whichever pill was pressed. Render around
 * the ChatView of a flow chat.
 */
export function FlowReferences({
  flow,
  onShowStep,
  composer = null,
  children
}: {
  flow: Flow;
  onShowStep: (stepId: string) => boolean;
  /** The chat's composer, for "Infoga i meddelandet"; null while there is none. */
  composer?: ComposerInsert | null;
  children: ReactNode;
}) {
  const [card, setCard] = useState<Card | null>(null);
  const value = useMemo<FlowReferencesValue>(
    () => ({
      flow,
      onShowStep,
      composer,
      card,
      openCard: (reference, anchor) =>
        setCard((current) => (current?.anchor === anchor ? null : { reference, anchor }))
    }),
    [flow, onShowStep, composer, card]
  );
  const close = ({ refocus = true } = {}) => {
    // Focus goes back to the pill the card came from, unless it went elsewhere.
    if (refocus) card?.anchor.focus();
    setCard(null);
  };
  return (
    <FlowReferencesContext.Provider value={value}>
      {children}
      <ReferenceCard card={card} onClose={close} />
    </FlowReferencesContext.Provider>
  );
}
