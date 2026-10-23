import { toast as sonner, type ExternalToast } from "sonner";

/**
 * How long a success or info toast stays up (ms): longer than sonner's 4 s,
 * so a short message can be read at a slower pace. Hovering the toasts or
 * leaving the tab pauses the timer, and every toast has a close button (the
 * Toaster in src/components/ui/sonner.tsx applies both).
 */
export const TOAST_DURATION_MS = 6000;

type Message = Parameters<typeof sonner.error>[0];

/** A toast that stays until it is closed has no duration to set. */
type PersistentToastOptions = Omit<ExternalToast, "duration">;

/**
 * The app's toasts; import this instead of `sonner` (lint enforces it).
 *
 * Errors and warnings stay until the user closes them: they tell the user
 * something to act on, and a time limit would take it away before everyone
 * has read it (WCAG 2.2.1, ACCESSIBILITY.md rule 10). Success and info
 * messages close after TOAST_DURATION_MS.
 */
export const toast = {
  success: (...args: Parameters<typeof sonner.success>) => sonner.success(...args),
  info: (...args: Parameters<typeof sonner.info>) => sonner.info(...args),
  warning: (message: Message, options?: PersistentToastOptions) =>
    sonner.warning(message, { ...options, duration: Infinity }),
  error: (message: Message, options?: PersistentToastOptions) =>
    sonner.error(message, { ...options, duration: Infinity })
};
