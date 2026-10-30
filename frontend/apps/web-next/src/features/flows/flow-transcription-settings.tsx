"use client";

import { MetadataListItem } from "@astryxdesign/core/MetadataList";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { Switch } from "@astryxdesign/core/Switch";
import { modelDisplayName } from "@/features/spaces/space-models";
import {
  speakerServiceState,
  TRANSCRIPTION_LANGUAGES,
  usableSpeakerServices,
  withSpeakerService,
  type SpeakerServiceLink,
  type SpeakerServiceState,
  type TranscriptionLanguage,
  type TranscriptionSettings
} from "./flow-transcription";

/** What the space offers for transcription: its models and the services granted to it. */
export type TranscriptionResources = {
  models: readonly { id: string; name: string; nickname?: string | null }[];
  services: readonly SpeakerServiceLink[];
};

type Translate = ReturnType<typeof useTranslations>;

const NONE = "__none";
const UNSET = "__unset";

const LANGUAGE_KEYS: Record<TranscriptionLanguage, string> = {
  sv: "flow_editor_tools_transcription_language_sv",
  en: "flow_editor_tools_transcription_language_en",
  auto: "flow_editor_tools_transcription_language_auto"
};

function lostSentence(state: SpeakerServiceState, required: boolean, usable: number, t: Translate) {
  if (!state.lost) return null;
  const reason =
    state.lost.reason === "removed"
      ? t("flow_editor_tools_speaker_service_lost_removed")
      : state.lost.reason === "disabled"
        ? t("flow_editor_tools_speaker_service_lost_disabled", { name: state.lost.name ?? "" })
        : t("flow_editor_tools_speaker_service_lost_classification", {
            name: state.lost.name ?? ""
          });
  const action =
    usable > 0
      ? required
        ? t("flow_editor_tools_speaker_service_lost_choose_required")
        : t("flow_editor_tools_speaker_service_lost_choose")
      : required
        ? t("flow_editor_tools_speaker_service_lost_none_required")
        : t("flow_editor_tools_speaker_service_lost_none");
  return `${reason} ${action}`;
}

function serviceName(service: SpeakerServiceLink, t: Translate): string {
  return service.is_default
    ? t("flow_editor_tools_speaker_service_default", { name: service.name })
    : service.name;
}

/** The settings as facts, for the settings' read view. */
export function TranscriptionSummary({
  settings,
  resources,
  required,
  modelMissing
}: {
  settings: TranscriptionSettings;
  resources: TranscriptionResources;
  required: boolean;
  modelMissing: boolean;
}) {
  const t = useTranslations();
  const model = resources.models.find((candidate) => candidate.id === settings.modelId);
  const state = speakerServiceState(settings, resources.services, required);
  const choice = settings.speakerService;
  return (
    <>
      <MetadataListItem label={t("flow_editor_tools_transcription_model")}>
        {model ? (
          modelDisplayName(model)
        ) : (
          <span className={modelMissing ? "text-ax-warning" : "text-ax-text-secondary"}>
            {settings.modelId
              ? t("flow_editor_tools_transcription_model_unavailable")
              : modelMissing
                ? t("flow_editor_tools_transcription_model_missing")
                : t("flow_editor_tools_transcription_model_none")}
          </span>
        )}
      </MetadataListItem>
      <MetadataListItem label={t("flow_editor_tools_transcription_language")}>
        {t(LANGUAGE_KEYS[settings.language])}
      </MetadataListItem>
      <MetadataListItem label={t("flow_editor_tools_speaker_service")}>
        {state.picked ? (
          state.picked.name
        ) : state.lost ? (
          <span className="text-ax-warning">
            {lostSentence(state, required, usableSpeakerServices(resources.services).length, t)}
          </span>
        ) : choice.kind === "none" ? (
          t("flow_editor_tools_speaker_service_none")
        ) : (
          <span className="text-ax-text-secondary">
            {t("flow_editor_tools_speaker_service_unset")}
          </span>
        )}
      </MetadataListItem>
      <MetadataListItem label={t("flow_editor_tools_speaker_labels")}>
        {state.labelled
          ? settings.maxSpeakers !== null && state.picked
            ? t("flow_editor_tools_speaker_labels_on_max", { count: settings.maxSpeakers })
            : t("flow_editor_tools_on")
          : t("flow_editor_tools_off")}
      </MetadataListItem>
    </>
  );
}

/**
 * The transcription settings in the settings form: the model, the language,
 * the service that times the words and labels speakers, and whether and how
 * many speakers are labelled. Nothing is chosen for the flow: a choice the
 * space can no longer use stays visible with its reason until it is changed.
 */
export function TranscriptionFields({
  settings,
  resources,
  takesAudio,
  required,
  modelMissing,
  maxSpeakersProblem,
  onChange,
  onMaxSpeakersInvalid
}: {
  settings: TranscriptionSettings;
  resources: TranscriptionResources;
  takesAudio: boolean;
  required: boolean;
  modelMissing: boolean;
  maxSpeakersProblem: boolean;
  onChange: (settings: TranscriptionSettings) => void;
  onMaxSpeakersInvalid: (invalid: boolean) => void;
}) {
  const t = useTranslations();
  const usable = usableSpeakerServices(resources.services);
  const state = speakerServiceState(settings, resources.services, required);
  const choice = settings.speakerService;
  const modelKnown = resources.models.some((model) => model.id === settings.modelId);
  const lost = lostSentence(state, required, usable.length, t);
  const on = takesAudio || settings.enabled;

  const serviceValue = state.picked
    ? state.picked.id
    : choice.kind === "none"
      ? NONE
      : choice.kind === "service"
        ? choice.id
        : UNSET;
  const serviceOptions = [
    ...(serviceValue === UNSET
      ? [{ value: UNSET, label: t("flow_editor_tools_speaker_service_choose") }]
      : []),
    ...(choice.kind === "service" && !state.picked
      ? [
          {
            value: choice.id,
            label: state.lost?.name ?? t("flow_editor_tools_speaker_service_gone")
          }
        ]
      : []),
    ...usable.map((service) => ({ value: service.id, label: serviceName(service, t) })),
    { value: NONE, label: t("flow_editor_tools_speaker_service_none"), disabled: required }
  ];

  const serviceNote = lost
    ? null
    : state.picked
      ? state.labelled
        ? t("flow_editor_tools_speaker_service_sends_speakers", { name: state.picked.name })
        : t("flow_editor_tools_speaker_service_sends", { name: state.picked.name })
      : choice.kind === "none"
        ? t("flow_editor_tools_speaker_service_none_note")
        : required
          ? t("flow_editor_tools_speaker_service_required")
          : t("flow_editor_tools_speaker_service_choose_hint");

  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
      <legend className="text-ax-text mb-1 p-0 text-sm font-semibold">
        {t("flow_editor_tools_transcription_heading")}
      </legend>
      {takesAudio ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_editor_tools_transcription_audio_always")}
        </Text>
      ) : (
        <Switch
          label={t("flow_editor_tools_transcription_enabled")}
          description={t("flow_editor_tools_transcription_enabled_description")}
          value={settings.enabled}
          onChange={(enabled) => onChange({ ...settings, enabled })}
        />
      )}
      {on ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Selector
              label={t("flow_editor_tools_transcription_model")}
              description={
                resources.models.length === 0
                  ? t("flow_editor_tools_transcription_no_models")
                  : undefined
              }
              options={[
                { value: NONE, label: t("flow_editor_tools_transcription_model_none") },
                ...resources.models.map((model) => ({
                  value: model.id,
                  label: modelDisplayName(model)
                })),
                ...(settings.modelId && !modelKnown
                  ? [
                      {
                        value: settings.modelId,
                        label: t("flow_editor_tools_transcription_model_gone")
                      }
                    ]
                  : [])
              ]}
              value={settings.modelId ?? NONE}
              onChange={(value) =>
                onChange({ ...settings, modelId: value === NONE ? null : value })
              }
              status={
                settings.modelId && !modelKnown
                  ? {
                      type: "warning",
                      message: t("flow_editor_tools_transcription_model_unavailable")
                    }
                  : modelMissing
                    ? {
                        type: "warning",
                        message: t("flow_editor_tools_transcription_model_missing")
                      }
                    : undefined
              }
              width="100%"
            />
            <Selector
              label={t("flow_editor_tools_transcription_language")}
              options={TRANSCRIPTION_LANGUAGES.map((language) => ({
                value: language,
                label: t(LANGUAGE_KEYS[language])
              }))}
              value={settings.language}
              onChange={(value) =>
                onChange({ ...settings, language: value as TranscriptionLanguage })
              }
              width="100%"
            />
          </div>
          {usable.length === 0 && !required && !state.lost ? (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {t("flow_editor_tools_speaker_service_none_in_space")}
            </Text>
          ) : (
            <>
              <Selector
                label={t("flow_editor_tools_speaker_service")}
                description={serviceNote ?? undefined}
                options={serviceOptions}
                value={serviceValue}
                onChange={(value) => {
                  if (value === UNSET) return;
                  onChange(withSpeakerService(settings, value === NONE ? null : value));
                }}
                status={lost ? { type: "warning", message: lost } : undefined}
                width="100%"
              />
              <Switch
                label={t("flow_editor_tools_speaker_labels")}
                description={
                  required
                    ? t("flow_editor_tools_speaker_labels_required")
                    : choice.kind === "none"
                      ? t("flow_editor_tools_speaker_labels_needs_service")
                      : t("flow_editor_tools_speaker_labels_description")
                }
                value={state.labelled}
                isDisabled={required || choice.kind === "none"}
                onChange={(speakerLabels) => onChange({ ...settings, speakerLabels })}
              />
              {state.labelled && state.picked ? (
                <NumberInput
                  label={t("flow_editor_tools_max_speakers")}
                  description={t("flow_editor_tools_max_speakers_description")}
                  value={settings.maxSpeakers}
                  onChange={(value) => {
                    const valid = value === null || (Number.isInteger(value) && value >= 1);
                    onMaxSpeakersInvalid(!valid);
                    if (valid) onChange({ ...settings, maxSpeakers: value });
                  }}
                  min={1}
                  isIntegerOnly
                  hasClear
                  isOptional
                  placeholder={t("flow_editor_tools_max_speakers_auto")}
                  status={
                    maxSpeakersProblem
                      ? { type: "error", message: t("flow_editor_tools_max_speakers_invalid") }
                      : undefined
                  }
                />
              ) : null}
            </>
          )}
        </>
      ) : null}
    </fieldset>
  );
}
