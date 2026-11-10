import type { RefObject } from "react";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";

/**
 * The label column of every flow read view (the step cards, a step's settings
 * as text, the request preview and the settings summary): one width, so their
 * values start at the same x on a page that shows several of them.
 */
export const FLOW_READ_LABEL = { position: "start", width: "9rem" } as const;
const LABEL_ON_TOP = { position: "top" } as const;

/** Below this width (px) the labels go on top: the label column plus room for a value. */
const SIDE_LABELS_MIN = 384;

/**
 * `FLOW_READ_LABEL` while `ref` has room for a value beside it, labels on top
 * where it is narrow (a phone, a column beside the chat). Until it is
 * measured, the screen decides.
 */
export function useFlowReadLabel(ref: RefObject<HTMLElement | null>) {
  const phone = usePhoneScreen();
  const narrow = useElementWidth(ref, (width) => width < SIDE_LABELS_MIN) ?? phone;
  return narrow ? LABEL_ON_TOP : FLOW_READ_LABEL;
}
