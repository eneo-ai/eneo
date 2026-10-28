import { useClipboard } from "@astryxdesign/core/hooks";
import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { toast } from "@/lib/toast";

/**
 * The app's copy-to-clipboard: Astryx `useClipboard` announces a copy and
 * keeps `isCopied` for the button's checkmark; a refused clipboard is told
 * in an error toast, so the user knows to copy by hand.
 */
export function useCopy(): { copy: (text: string) => Promise<boolean>; isCopied: boolean } {
  const t = useTranslations();
  const { copy: write, isCopied } = useClipboard({ announce: t("copied_to_clipboard") });
  const copy = useCallback(
    async (text: string) => {
      const copied = await write(text);
      if (!copied) toast.error(t("copy_failed"));
      return copied;
    },
    [write, t]
  );
  return { copy, isCopied };
}
