import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { KEYBOARD } from "@/components/astryx/keyboard-hints";
import { TextInput } from "@/components/astryx/text-input";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import {
  highestFirst,
  type SecurityClassification
} from "@/features/admin/security-classifications/security-classifications";
import { getErrorMessage } from "@/lib/api/errors";
import { describeCheck } from "./transcription-service-check";
import {
  endpointBase,
  endpointProblem,
  isServiceNameTaken,
  type TranscriptionService,
  type TranscriptionServiceCreate,
  type TranscriptionServiceLastCheck,
  type TranscriptionServiceUpdate
} from "./transcription-services";

const NONE = "none";
// Astryx's TextInput type has no "url"; the phone keyboard still gets "/" and ".".
const ADDRESS_KEYBOARD = { ...KEYBOARD.identifier, inputMode: "url" } as const;

/**
 * Connect or edit one speaker identification service. The owner mounts it
 * afresh for each opening (a `key`), so the form starts from the saved
 * settings, or empty, and a cancelled edit is forgotten.
 *
 * The key is write-only: on edit a blank key keeps the saved one, and a moved
 * address needs a new key because the backend never sends the stored key to
 * another destination. A new service is tested at once and the dialog stays
 * open on it, so a wrong key or address can be fixed in place.
 */
export function TranscriptionServiceDialog({
  open,
  onOpenChange,
  service,
  classifications,
  check,
  checking,
  onCreate,
  onUpdate,
  onTest
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The saved service to edit; null connects a new one. Read when mounted. */
  service: TranscriptionService | null;
  classifications: SecurityClassification[];
  /** The latest check of the saved settings. */
  check?: TranscriptionServiceLastCheck | null;
  /** A check of the saved settings is running. */
  checking: boolean;
  /** The owner saves; a rejection keeps the dialog open with the entered values. */
  onCreate: (body: TranscriptionServiceCreate) => Promise<TranscriptionService>;
  onUpdate: (id: string, body: TranscriptionServiceUpdate) => Promise<TranscriptionService>;
  onTest: () => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const formId = useId();
  // The menu item that opened the dialog is gone once it is open.
  const noTrigger = useRef<HTMLElement>(null);
  useReturnFocus(open, noTrigger);
  const nameRef = useRef<HTMLInputElement>(null);
  const addressRef = useRef<HTMLInputElement>(null);
  const keyRef = useRef<HTMLInputElement>(null);
  const doneRef = useRef<HTMLButtonElement>(null);

  // Connecting turns the dialog into the editor of the new service.
  const [saved, setSaved] = useState(service);
  const [connected, setConnected] = useState(false);
  // What was last saved, not what the service reads back: with classification
  // enforcement off the API reads every classification as none.
  const [savedClassificationId, setSavedClassificationId] = useState(
    service?.security_classification?.id ?? NONE
  );
  const [savedDefault, setSavedDefault] = useState(service?.is_default ?? false);
  const [name, setName] = useState(service?.name ?? "");
  const [address, setAddress] = useState(service?.endpoint_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [classificationId, setClassificationId] = useState(savedClassificationId);
  const [isDefault, setIsDefault] = useState(savedDefault);
  const [attempted, setAttempted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [saveFirst, setSaveFirst] = useState(false);
  const [nameTaken, setNameTaken] = useState(false);
  const [addressError, setAddressError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  // Where focus goes once a save has answered and the form shows the result:
  // once connected the connect button is gone, so the way out ("Klar"); after
  // a refusal, the field it is about.
  const focusAfter = useRef<"done" | "name" | "address" | null>(null);
  const setFocusAfter = (target: "done" | "name" | "address") => (focusAfter.current = target);
  // After every render: the one that shows the save's answer moves focus once.
  useEffect(() => {
    if (!focusAfter.current) return;
    ({ done: doneRef, name: nameRef, address: addressRef })[focusAfter.current].current?.focus();
    focusAfter.current = null;
  });

  const addressMoved = saved !== null && endpointBase(address) !== endpointBase(saved.endpoint_url);
  const nameMissing = !name.trim();
  const addressMissing = !address.trim();
  const keyMissing = (saved === null || addressMoved) && !apiKey.trim();
  const nameChanged = saved !== null && name.trim() !== saved.name;
  const classificationChanged = classificationId !== savedClassificationId;
  const defaultChanged = saved !== null && isDefault !== savedDefault;
  const dirty =
    saved !== null &&
    (nameChanged || addressMoved || apiKey !== "" || classificationChanged || defaultChanged);

  const nameProblem = nameTaken
    ? t("speaker_service_name_taken")
    : attempted && nameMissing
      ? t("speaker_service_name_required")
      : null;
  const addressProblem =
    addressError ?? (attempted && addressMissing ? t("speaker_service_address_required") : null);
  const keyProblem =
    attempted && keyMissing
      ? addressMoved
        ? t("speaker_service_api_key_new_address")
        : t("speaker_service_api_key_required")
      : null;
  // Said before submitting, calmly; it turns into an error only on a save attempt.
  const keyNote =
    addressMoved && keyMissing
      ? t("speaker_service_api_key_new_address")
      : saved
        ? t("speaker_service_api_key_edit_help")
        : undefined;

  function requestOpenChange(next: boolean) {
    if (!next && submitting) return;
    onOpenChange(next);
  }

  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if (nameMissing || addressMissing || keyMissing) {
      // Rendered before focus moves, so the field is read with its error (WCAG 3.3.1).
      flushSync(() => setAttempted(true));
      (nameMissing ? nameRef : addressMissing ? addressRef : keyRef).current?.focus();
      return;
    }
    setAttempted(true);
    setSubmitting(true);
    setNameTaken(false);
    setAddressError(null);
    setFormError(null);
    const classification = classificationId === NONE ? null : { id: classificationId };
    try {
      if (saved) {
        // Only what the administrator changed: the read shape is not the stored
        // one (with enforcement off a stored classification reads as null), so
        // echoing it back would overwrite what was never touched.
        const updated = await onUpdate(saved.id, {
          ...(nameChanged && { name: name.trim() }),
          ...(classificationChanged && { security_classification: classification }),
          ...(addressMoved && { endpoint_url: address.trim() }),
          ...(apiKey.trim() && { api_key: apiKey.trim() }),
          ...(defaultChanged && { is_default: isDefault })
        });
        // A service just connected stays open, so the new test is seen too.
        if (!connected) {
          onOpenChange(false);
          return;
        }
        setSaved(updated);
        // As stored: without a trailing "/" or "/v1".
        setAddress(updated.endpoint_url);
        setSavedClassificationId(classificationId);
        setSavedDefault(isDefault);
      } else {
        const created = await onCreate({
          name: name.trim(),
          endpoint_url: address.trim(),
          api_key: apiKey.trim(),
          is_enabled: true,
          security_classification: classification
        });
        setSaved(created);
        setConnected(true);
        setAddress(created.endpoint_url);
        setSavedClassificationId(classificationId);
        setApiKey("");
        setAttempted(false);
        // Marked in a second step, through the one path that takes the mark
        // from the service that had it. If it fails the service stays
        // connected and the box stays ticked, so saving tries again.
        if (isDefault) {
          setSaved(await onUpdate(created.id, { is_default: true }));
          setSavedDefault(true);
        }
        setFocusAfter("done");
        return;
      }
      setApiKey("");
      setAttempted(false);
      setFocusAfter("done");
    } catch (error) {
      // The entered values stay; the message goes to the field it is about,
      // and so does focus.
      const problem = endpointProblem(error, t);
      if (isServiceNameTaken(error)) {
        setNameTaken(true);
        setFocusAfter("name");
      } else if (problem !== null) {
        setAddressError(problem);
        setFocusAfter("address");
      } else {
        setFormError(getErrorMessage(error, t));
      }
    } finally {
      setSubmitting(false);
    }
  }

  function test() {
    setSaveFirst(dirty);
    if (dirty) announce(t("speaker_service_save_first"));
    else onTest();
  }

  const title =
    connected && saved
      ? t("speaker_service_dialog_connected_title", { name: saved.name })
      : saved
        ? t("speaker_service_dialog_edit_title", { name: saved.name })
        : t("speaker_service_dialog_create_title");
  const summary = check ? describeCheck(check, t) : null;

  return (
    <Dialog
      isOpen={open}
      onOpenChange={requestOpenChange}
      purpose="form"
      width={520}
      maxHeight="calc(100dvh - 2rem)"
    >
      <Layout
        header={
          <DialogHeader
            title={title}
            subtitle={t("speaker_service_dialog_description")}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          <LayoutContent>
            <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
              {formError && <Banner role="alert" status="error" title={formError} />}
              <FormLayout defaultOptionality="optional">
                <TextInput
                  ref={nameRef}
                  label={t("name")}
                  value={name}
                  onChange={setName}
                  isRequired
                  isDisabled={submitting}
                  autoComplete="off"
                  status={nameProblem ? { type: "error", message: nameProblem } : undefined}
                />
                <TextInput
                  ref={addressRef}
                  label={t("speaker_service_address")}
                  description={addressProblem ? undefined : t("speaker_service_address_help")}
                  value={address}
                  onChange={(value) => {
                    setAddress(value);
                    setAddressError(null);
                  }}
                  isRequired
                  isDisabled={submitting}
                  autoComplete="off"
                  {...ADDRESS_KEYBOARD}
                  status={addressProblem ? { type: "error", message: addressProblem } : undefined}
                />
                <TextInput
                  ref={keyRef}
                  type="password"
                  label={t("speaker_service_api_key")}
                  description={keyProblem ? undefined : keyNote}
                  value={apiKey}
                  onChange={setApiKey}
                  isRequired={saved === null || addressMoved}
                  isDisabled={submitting}
                  // A service's key is not the administrator's own password: "new-password"
                  // keeps password managers from filling the sign-in password in, which
                  // they do over "off" on a password field.
                  autoComplete="new-password"
                  placeholder={
                    saved && !addressMoved
                      ? t("speaker_service_api_key_saved_placeholder")
                      : undefined
                  }
                  status={keyProblem ? { type: "error", message: keyProblem } : undefined}
                />
                <Selector
                  label={t("speaker_service_column_classification")}
                  description={t("speaker_service_classification_help")}
                  options={[
                    { value: NONE, label: t("speaker_service_classification_none") },
                    ...highestFirst(classifications).map((classification) => ({
                      value: classification.id,
                      label: classification.name
                    }))
                  ]}
                  value={classificationId}
                  onChange={setClassificationId}
                  isDisabled={submitting}
                  width="100%"
                />
                <CheckboxInput
                  label={t("speaker_service_default_label")}
                  description={t("speaker_service_default_help")}
                  value={isDefault}
                  onChange={setIsDefault}
                  isDisabled={submitting}
                />
              </FormLayout>
              {saved &&
                (saveFirst && dirty ? (
                  <Text type="supporting">{t("speaker_service_save_first")}</Text>
                ) : checking ? (
                  // The same callout shape as the result, so the dialog keeps its height.
                  <Banner
                    status="info"
                    title={t("speaker_service_testing_connection")}
                    description={t("speaker_service_testing_connection_detail")}
                  />
                ) : summary ? (
                  <Banner
                    status={summary.tone}
                    title={summary.label}
                    description={summary.detail}
                  />
                ) : null)}
            </form>
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <div className="flex flex-wrap items-center justify-between gap-2">
              {saved ? (
                <Button
                  label={checking ? t("speaker_service_testing") : t("speaker_service_test")}
                  // Keeps focus while the check runs; a press meanwhile, or
                  // during a save, is ignored.
                  isLoading={checking}
                  isInterruptible
                  onClick={() => {
                    if (!checking && !submitting) test();
                  }}
                />
              ) : (
                <span />
              )}
              <div className="flex flex-wrap justify-end gap-2">
                {saved && !dirty && !submitting ? (
                  // Everything is saved: one way out, nothing to cancel.
                  <Button
                    ref={doneRef}
                    variant="primary"
                    label={t("done")}
                    onClick={() => onOpenChange(false)}
                  />
                ) : (
                  <>
                    <Button
                      label={t("cancel")}
                      isDisabled={submitting}
                      onClick={() => requestOpenChange(false)}
                    />
                    <Button
                      type="submit"
                      form={formId}
                      variant="primary"
                      label={saved ? t("save") : t("speaker_service_connect_submit")}
                      // Keeps focus while saving; the form ignores a second press.
                      isLoading={submitting}
                      isInterruptible
                    />
                  </>
                )}
              </div>
            </div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
