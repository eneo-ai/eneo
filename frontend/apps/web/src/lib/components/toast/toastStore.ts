// Copyright (c) 2026 Sundsvalls Kommun

import { createToaster } from "@melt-ui/svelte";

export type ToastType = "success" | "error" | "info" | "warning";

export interface ToastData {
  type: ToastType;
  message: string;
}

const {
  elements: { content, title, description, close },
  helpers,
  states: { toasts },
  actions: { portal }
} = createToaster<ToastData>({
  closeDelay: 4000,
  type: "foreground"
});

export { content, title, description, close, toasts, portal };

// Convenience functions
export function success(message: string, closeDelay?: number) {
  return helpers.addToast({
    data: { type: "success", message },
    closeDelay: closeDelay ?? 3000
  });
}

export function error(message: string, closeDelay?: number) {
  return helpers.addToast({
    data: { type: "error", message },
    closeDelay: closeDelay ?? 5000
  });
}

export function info(message: string, closeDelay?: number) {
  return helpers.addToast({
    data: { type: "info", message },
    closeDelay: closeDelay ?? 3000
  });
}

export function warning(message: string, closeDelay?: number) {
  return helpers.addToast({
    data: { type: "warning", message },
    closeDelay: closeDelay ?? 4000
  });
}

// Default export for compatibility
export const toast = {
  success,
  error,
  info,
  warning
};
