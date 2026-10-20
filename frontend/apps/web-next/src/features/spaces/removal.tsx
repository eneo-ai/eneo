"use client";

import { useMutation, type MutationKey } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { createContext, use, useRef, type RefObject } from "react";
import { toastApiError } from "@/lib/api/toast";
import { focusAfterRemoval } from "@/lib/focus-after-removal";
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
 * focus to the row that took the removed one's place when `anchor` (a control
 * in the row) is given, else to `focusTarget` or the nearest
 * `RemovalFocusScope` target; `rescueFocus` only acts when focus was actually
 * lost. Errors are toasted unless `onError` is given.
 */
export function useRemovalMutation<TData = unknown, TVariables = void>({
  mutationKey,
  mutationFn,
  refresh,
  onRemoved,
  onError,
  focusTarget,
  anchor
}: {
  /** For a page that must tell its own removal from the item vanishing otherwise. */
  mutationKey?: MutationKey;
  mutationFn: (variables: TVariables) => Promise<TData>;
  refresh: () => Promise<unknown>;
  onRemoved?: (data: TData, variables: TVariables) => void;
  onError?: (error: Error) => void;
  /** For a list that owns the mutation itself (so no scope is above it). */
  focusTarget?: FocusTarget;
  /** A control in the removed item's row (its menu), to find the neighbouring row by. */
  anchor?: FocusTarget;
}) {
  const t = useTranslations();
  const scopeTarget = use(RemovalFocusContext);
  const target = focusTarget ?? scopeTarget;
  const neighbour = useRef<() => HTMLElement | null>(() => null);
  return useMutation({
    mutationKey,
    mutationFn,
    onMutate: () => {
      neighbour.current = focusAfterRemoval(anchor?.current ?? null);
    },
    onSuccess: async (data, variables) => {
      await refresh();
      onRemoved?.(data, variables);
      const next = neighbour.current;
      // Keep the fallback on this page if it unmounts before the delayed checks.
      const page = document.getElementById("main-content");
      rescueFocus(() => next() ?? target?.current ?? page);
    },
    onError: onError ?? ((error) => toastApiError(error, t))
  });
}
