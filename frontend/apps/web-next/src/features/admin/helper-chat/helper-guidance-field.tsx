import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { revealProblems } from "@/components/composites/field-problem";
import { LeaveConfirmation } from "@/components/composites/leave-confirmation";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { settingSwitchScope } from "@/features/admin/use-setting-switch";
import { browserApi } from "@/lib/api/browser";
import {
  guidanceLength,
  guidanceRefusalMessage,
  guidanceTooLongMessage,
  HELPER_CHAT_POLICY_KEY,
  HELPER_CHAT_POLICY_QUEUE,
  updateHelperChatPolicy,
  type HelperChatPolicy
} from "./helper-chat-policy";

type Status = "saved" | "unchanged" | null;

/**
 * The organisation's guidance for the helper: plain text added to its
 * built-in instructions, at most the length the API reports. An explicit
 * save. Save is never disabled: text over the maximum shows the problem at
 * the field, which takes focus, and nothing is sent; a refused save shows at
 * the field too and keeps the text. The counter (Astryx) describes the field
 * and speaks only when the text nears or passes the maximum.
 */
export function HelperGuidanceField({ policy }: { policy: HelperChatPolicy }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const saved = policy.guidance;
  const max = policy.guidance_max_length;

  const [draft, setDraft] = useState(saved);
  // Adjusted during render: an untouched field follows a guidance saved elsewhere.
  const [seen, setSeen] = useState(saved);
  if (saved !== seen) {
    setSeen(saved);
    if (draft === seen) setDraft(saved);
  }
  const [checked, setChecked] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);

  const save = useMutation({
    mutationFn: (guidance: string) => updateHelperChatPolicy(browserApi, { guidance }),
    scope: settingSwitchScope(HELPER_CHAT_POLICY_QUEUE),
    onSuccess: (next, sent) => {
      // The server keeps the text without surrounding whitespace; text typed
      // while it saved stays as typed.
      setDraft((current) => (current === sent ? next.guidance : current));
      queryClient.setQueryData(HELPER_CHAT_POLICY_KEY, next);
      setChecked(false);
      setStatus("saved");
      announce(t("admin_helper_guidance_saved"));
    },
    onError: (error) =>
      revealProblems(() => setRefusal(guidanceRefusalMessage(error, max, t)), fieldRef.current)
  });

  const dirty = draft !== saved;
  const tooLong = guidanceLength(draft) > max;
  const problem = checked && tooLong ? guidanceTooLongMessage(max, t) : refusal;
  const statusText = dirty
    ? t("admin_helper_guidance_unsaved")
    : status === "saved"
      ? t("admin_helper_guidance_saved")
      : status === "unchanged"
        ? t("form_nothing_to_save")
        : null;

  function edit(value: string) {
    setDraft(value);
    setRefusal(null);
    setStatus(null);
  }

  function submit() {
    if (save.isPending) return;
    if (tooLong) {
      revealProblems(() => {
        setChecked(true);
        setStatus(null);
      }, fieldRef.current);
      return;
    }
    if (!dirty) {
      setStatus("unchanged");
      announce(t("form_nothing_to_save"));
      return;
    }
    setRefusal(null);
    setStatus(null);
    save.mutate(draft);
  }

  function discard() {
    setDraft(saved);
    setChecked(false);
    setRefusal(null);
    setStatus(null);
  }

  return (
    <SettingsGroup id="helper-guidance" title={t("admin_helper_guidance_group")}>
      <form
        className="flex flex-col gap-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <TextArea
          ref={fieldRef}
          label={t("admin_helper_guidance_label")}
          description={t("admin_helper_guidance_description")}
          placeholder={t("admin_helper_guidance_placeholder")}
          value={draft}
          onChange={edit}
          rows={8}
          maxLength={max}
          width="100%"
          status={problem ? { type: "error", message: problem } : undefined}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            variant="primary"
            label={t("admin_helper_guidance_save")}
            // Keeps focus while it saves; a second press is ignored above.
            isLoading={save.isPending}
            isInterruptible
          />
          <Button
            label={t("discard_changes")}
            isDisabled={!dirty || save.isPending}
            onClick={discard}
          />
          {statusText ? (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {statusText}
            </Text>
          ) : null}
        </div>
        <LeaveConfirmation active={dirty || save.isPending} />
      </form>
    </SettingsGroup>
  );
}
