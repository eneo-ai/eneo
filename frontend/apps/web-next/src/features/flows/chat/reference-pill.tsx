import { Button } from "@astryxdesign/core/Button";
import { Popover } from "@astryxdesign/core/Popover";
import { Text } from "@astryxdesign/core/Text";
import { CircleAlert, Plug, TriangleAlert } from "lucide-react";
import { useTranslations } from "use-intl";
import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
  type RefObject
} from "react";
import type { ComposerInsert } from "@/features/chat/chat-references";
import { insertParts, type InsertPart } from "@/features/references/reference-menu";
import { PillButton, ReferenceToken } from "@/features/references/reference-pill";
import { cn } from "@/lib/utils";
import { meaningLabel, readWarning } from "../editor/step-labels";
import type { FlowPublic } from "../editor/step-types";
import type { FieldAnchor } from "../editor/field-problems";
import { stepLabel } from "../flow-labels";
import { connectionToOpen, stepConnections } from "./connections";
import {
  referenceHint,
  referenceParts,
  referenceStep,
  referenceTone,
  valueOf,
  valueWhat,
  type Reference
} from "./references";

type Translate = ReturnType<typeof useTranslations>;
type Flow = Pick<FlowPublic, "steps" | "metadata_json">;

type Card = { reference: Reference; anchor: HTMLElement };

/** The flow a chat is about, how to show one of its steps, and the one open reference card. */
type FlowReferencesValue = {
  flow: Flow;
  /** Brings the step's card into view; false when the card is not on the page. */
  onShowStep: (stepId: string) => boolean;
  /** Opens the step's editor at a connection field ("Anslut tjänst"); absent, it is not offered. */
  onConnectStep?: (stepId: string, anchor: FieldAnchor) => void;
  /** The chat's composer, to put a reference into; null while there is none. */
  composer: ComposerInsert | null;
  card: Card | null;
  openCard: (reference: Reference, anchor: HTMLElement) => void;
};

const FlowReferencesContext = createContext<FlowReferencesValue | null>(null);

export function useFlowReferences(): FlowReferencesValue | null {
  return useContext(FlowReferencesContext);
}

/**
 * What a pill says, the same as the editor's chips: "Steg 1: Extrahera" for a
 * step, "Steg 1: Extrahera › fastighet" for a value.
 */
export function referenceLabel(reference: Reference, flow: Flow, t: Translate): string {
  if (reference.kind === "step") {
    return reference.step ? stepLabel(reference.step, t) : reference.name;
  }
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
  if (referenceTone(reference) === "missing") {
    return meaningLabel(reference.meaning, reference.token, flow, t);
  }
  // Nothing the flow resolves: shorthand such as {{step_1...}}, or a name it has no value for.
  if (reference.meaning.kind === "other") {
    return t("flows_chat_reference_unknown", { token: reference.token });
  }
  return readWarning(reference.meaning, flow, t);
}

/** A value the step provides, as a pill: pressed, it goes into the message when there is one. */
function SuggestedPill({ token }: { token: string }) {
  const refs = useFlowReferences()!;
  const reference = valueOf(token, refs.flow);
  if (!refs.composer) return <ReferencePill reference={reference} />;
  const composer = refs.composer;
  return (
    <PillButton onClick={() => insertReference(composer, reference)}>
      <ReferencePill reference={reference} />
    </PillButton>
  );
}

/** A reference as the pill the composer holds: its value is the reference as written. */
function referenceToken(reference: Reference) {
  return { value: reference.raw, render: () => <ReferencePill reference={reference} /> };
}

/** Puts a reference into the composer as a pill at the caret, focus with it. */
export function insertReference(composer: ComposerInsert, reference: Reference) {
  composer.insertToken(referenceToken(reference));
}

/**
 * Puts a prepared message into the composer at the caret, as if the person
 * had written it: its text as typed, each step mention and value reference
 * as the pill a pick from the reference menu makes. Nothing is sent.
 */
export function insertMessage(composer: ComposerInsert, text: string, flow: Flow) {
  insertParts(
    composer,
    referenceParts(text, flow).map((part): InsertPart =>
      part.kind === "text" ? part : { kind: "token", token: referenceToken(part) }
    )
  );
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
      <CircleAlert aria-hidden="true" className="size-3.5" />
    ) : tone === "warning" ? (
      <TriangleAlert aria-hidden="true" className="size-3.5" />
    ) : undefined;
  return (
    <ReferenceToken
      color={color}
      icon={icon}
      label={referenceLabel(reference, refs.flow, t)}
      className={className}
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
    <PillButton
      ref={setElement}
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={(event) => refs.openCard(reference, event.currentTarget)}
      className="align-middle"
    >
      <ReferencePill reference={reference} />
    </PillButton>
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
  const hint = reference ? referenceHint(reference, refs.flow) : null;
  // The services the step talks to, and the one "Anslut tjänst" opens.
  const connections = step ? stepConnections(step) : [];
  const toConnect = connectionToOpen(connections);
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
            {hint ? (
              <div className="flex flex-col gap-1.5">
                <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                  {t("flows_chat_reference_step_offers", { step: stepLabel(hint.step, t) })}
                </Text>
                <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                  {hint.choices.map((choice) => (
                    <li key={choice.token}>
                      <SuggestedPill token={choice.token} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {connections.length > 0 ? (
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
                {connections.map((connection) => (
                  <li key={connection.anchor} className="flex items-start gap-1.5">
                    <Plug
                      aria-hidden="true"
                      className="text-ax-text-secondary mt-0.5 size-4 shrink-0"
                    />
                    <span>
                      {t(
                        connection.direction === "input"
                          ? "flows_chat_reference_connection_input"
                          : "flows_chat_reference_connection_output",
                        { host: connection.host || "?" }
                      )}
                      {" · "}
                      <span className={connection.configured ? undefined : "text-ax-warning"}>
                        {t(
                          connection.authMode === "none"
                            ? "flows_chat_reference_connection_open"
                            : connection.configured
                              ? "flows_chat_reference_connection_stored"
                              : "flows_chat_reference_connection_missing"
                        )}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {step?.id && refs.onConnectStep && toConnect ? (
                <Button
                  size="sm"
                  variant={toConnect.configured ? "ghost" : undefined}
                  label={t("flows_chat_reference_connect")}
                  onClick={() => {
                    refs.onConnectStep?.(step.id!, toConnect.anchor);
                    onClose();
                  }}
                />
              ) : null}
              {refs.composer ? (
                <Button
                  size="sm"
                  label={t("flows_chat_reference_insert")}
                  onClick={() => {
                    // The pill goes to the caret and focus with it.
                    if (refs.composer) insertReference(refs.composer, reference);
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
  onConnectStep,
  composer = null,
  children
}: {
  flow: Flow;
  onShowStep: (stepId: string) => boolean;
  onConnectStep?: (stepId: string, anchor: FieldAnchor) => void;
  /** The chat's composer, for "Infoga i meddelandet"; null while there is none. */
  composer?: ComposerInsert | null;
  children: ReactNode;
}) {
  const [card, setCard] = useState<Card | null>(null);
  const value = useMemo<FlowReferencesValue>(
    () => ({
      flow,
      onShowStep,
      onConnectStep,
      composer,
      card,
      openCard: (reference, anchor) =>
        setCard((current) => (current?.anchor === anchor ? null : { reference, anchor }))
    }),
    [flow, onShowStep, onConnectStep, composer, card]
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
