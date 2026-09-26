"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toastApiError } from "@/lib/api/toast";

/**
 * A tenant-wide on/off setting behind a switch. The switch shows the latest
 * press at once and stays enabled (and focused) while saving; presses are saved
 * one after another, so a press during a save is sent when it finishes instead
 * of being dropped. Each save refreshes the server layout, so the new setting
 * reaches the whole app; a failed save shows an error and falls back to the
 * last saved value.
 *
 * Not the Switch's own `changeAction`: its busy state has a hard-coded English
 * label (see AGENTS.md → Reuse before you build).
 */
export function useSettingSwitch(
  /** Unique per setting: saves of one setting are queued behind each other. */
  id: string,
  initial: boolean,
  save: (enabled: boolean) => Promise<unknown>
): [boolean, (enabled: boolean) => void] {
  const t = useTranslations();
  const router = useRouter();
  const [saved, setSaved] = useState(initial);
  const mutation = useMutation({
    mutationFn: save,
    scope: { id: `tenant-setting:${id}` },
    onSuccess: (_data, enabled) => {
      setSaved(enabled);
      router.refresh();
    },
    onError: (error) => toastApiError(error, t)
  });
  return [mutation.isPending ? mutation.variables : saved, mutation.mutate];
}
