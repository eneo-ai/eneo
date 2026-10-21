"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toastApiError } from "@/lib/api/toast";

export type SettingSwitchOptions = {
  /**
   * After a save. By default the server layout refreshes, so a tenant setting
   * reaches the whole app; a setting read through React Query refreshes its
   * query here instead.
   */
  onSaved?: (enabled: boolean) => void;
  /** A failed save. By default an error toast. */
  onError?: (error: unknown) => void;
  /**
   * Saves in one queue run one after another; by default each setting has
   * its own. Settings saved through one endpoint can share a queue.
   */
  queue?: string;
};

/**
 * An on/off setting behind a switch that saves on toggle. The switch shows the
 * latest press at once and stays enabled (and focused) while saving; presses
 * are saved one after another, so a press during a save is sent when it
 * finishes instead of being dropped. A failed save shows an error and falls
 * back to the last saved value. When the server's value changes (the refresh
 * after a save, or a change made elsewhere) the switch follows it.
 *
 * Returns the value to show, the switch's change handler, and whether a save
 * is running (for `aria-busy` on a legacy Switch).
 *
 * Not the Astryx Switch's own `changeAction`: its busy state has a hard-coded
 * English label (see AGENTS.md → Reuse before you build).
 */
export function useSettingSwitch(
  /** Unique per setting: saves of one setting are queued behind each other. */
  id: string,
  /** The setting as the server has it. */
  initial: boolean,
  save: (enabled: boolean) => Promise<unknown>,
  { onSaved, onError, queue }: SettingSwitchOptions = {}
): [boolean, (enabled: boolean) => void, boolean] {
  const t = useTranslations();
  const router = useRouter();
  const [saved, setSaved] = useState(initial);
  // Adjusted during render, not in an effect: the switch never shows a value
  // the server has moved on from.
  const [server, setServer] = useState(initial);
  if (initial !== server) {
    setServer(initial);
    setSaved(initial);
  }
  const mutation = useMutation({
    mutationFn: save,
    scope: { id: `setting-switch:${queue ?? id}` },
    onSuccess: (_data, enabled) => {
      setSaved(enabled);
      if (onSaved) onSaved(enabled);
      else router.refresh();
    },
    onError: (error) => (onError ? onError(error) : toastApiError(error, t))
  });
  return [mutation.isPending ? mutation.variables : saved, mutation.mutate, mutation.isPending];
}
