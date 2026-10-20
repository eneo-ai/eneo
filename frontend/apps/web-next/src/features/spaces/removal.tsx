"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { createContext, use, type RefObject } from "react";
import { toastApiError } from "@/lib/api/toast";
import { rescueFocus } from "@/lib/focus-rescue";

type FocusTarget = RefObject<HTMLElement | null>;

const RemovalFocusContext = createContext<FocusTarget | null>(null);

/**
 * Marks where focus goes when an item of the list inside is deleted or moved
 * to another space: the list's heading or tab panel (an element with
 * `tabIndex={-1}`, e.g. `PageHeader`'s `headingRef`). Outside any scope focus
 * goes to the page panel, `main#main-content`.
 */
export function RemovalFocusScope({
  target,
  children
}: {
  target: FocusTarget;
  children: React.ReactNode;
}) {
  return <RemovalFocusContext value={target}>{children}</RemovalFocusContext>;
}

/**
 * The one mutation for actions that take an item out of the list it is shown
 * in (delete, move to another space). Its row, the row's menu button and the
 * dialog that confirmed the action disappear once the list refetches, which
 * would leave keyboard focus on <body> (ACCESSIBILITY.md rule 2). On success
 * it waits for `refresh` (the list's invalidation, so the dialog stays pending
 * until the item is gone), then runs `onRemoved` (close the dialog) and moves
 * focus to `focusTarget`, or the nearest `RemovalFocusScope` target;
 * `rescueFocus` only acts when focus was actually lost. Errors are toasted
 * unless `onError` is given.
 */
export function useRemovalMutation<TData = unknown, TVariables = void>({
  mutationFn,
  refresh,
  onRemoved,
  onError,
  focusTarget
}: {
  mutationFn: (variables: TVariables) => Promise<TData>;
  refresh: () => Promise<unknown>;
  onRemoved?: (data: TData, variables: TVariables) => void;
  onError?: (error: Error) => void;
  /** For a list that owns the mutation itself (so no scope is above it). */
  focusTarget?: FocusTarget;
}) {
  const t = useTranslations();
  const scopeTarget = use(RemovalFocusContext);
  const target = focusTarget ?? scopeTarget;
  return useMutation({
    mutationFn,
    onSuccess: async (data, variables) => {
      await refresh();
      onRemoved?.(data, variables);
      rescueFocus(target?.current ?? document.getElementById("main-content"));
    },
    onError: onError ?? ((error) => toastApiError(error, t))
  });
}
