/**
 * The place in the step editor where the author fixes an issue the banner
 * lists. The tool section marks its places with `data-step-focus` (and an
 * argument row with `data-tool-argument`), so the editor can land there
 * without holding the section's elements.
 */
export type StepFocusTarget =
  { kind: "tool" } | { kind: "tool_arguments" } | { kind: "tool_argument"; name: string };

const FOCUSABLE =
  "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";

function anchorFor(root: ParentNode, target: StepFocusTarget): HTMLElement | null {
  const tool = root.querySelector<HTMLElement>("[data-step-focus='tool']");
  if (target.kind === "tool") return tool;
  const toolArguments = root.querySelector<HTMLElement>("[data-step-focus='tool_arguments']");
  // The JSON field, where a text without a row of its own is typed.
  if (target.kind === "tool_arguments") {
    return root.querySelector<HTMLElement>("[data-tool-arguments-json]") ?? toolArguments ?? tool;
  }
  const row = Array.from(root.querySelectorAll<HTMLElement>("[data-tool-argument]")).find(
    (element) => element.dataset.toolArgument === target.name
  );
  // A tool whose arguments are one JSON field has no row per argument.
  return row ?? toolArguments ?? tool;
}

/**
 * Scrolls the target's place into view and focuses its first control the
 * author has to change (a value marked invalid), else its first control.
 * True when a control took the focus.
 */
export function focusStepTarget(root: ParentNode, target: StepFocusTarget): boolean {
  const anchor = anchorFor(root, target);
  if (!anchor) return false;
  const control =
    anchor.querySelector<HTMLElement>("[aria-invalid='true']") ??
    anchor.querySelector<HTMLElement>(FOCUSABLE);
  // The control itself is scrolled to: a tall place can hold it below the view.
  (control ?? anchor).scrollIntoView({ block: "center" });
  control?.focus({ preventScroll: true });
  return control !== null && control === document.activeElement;
}
