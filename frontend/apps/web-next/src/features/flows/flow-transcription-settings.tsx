import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { Switch } from "@astryxdesign/core/Switch";
import { modelDisplayName } from "@/features/spaces/space-models";
import {
  liveModels,
  liveModelState,
  speakerServiceState,
  TRANSCRIPTION_LANGUAGES,
  usableSpeakerServices,
  withSpeakerService,
  type LiveModelState,
  type SpeakerServiceLink,
  type SpeakerServiceState,
  type TranscriptionLanguage,
  type TranscriptionModelLink,
  type TranscriptionResources,
  type TranscriptionSettings
} from "./flow-transcription";

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

/** What the live model setting does now, below its field; null when its status says it. */
function liveModelNote(state: LiveModelState, t: Translate): string | null {
  switch (state.kind) {
    case "transcription_model":
      return state.streams
        ? t("flow_editor_tools_live_model_same_note")
        : t("flow_editor_tools_live_model_off_note");
    case "picked":
      return t("flow_editor_tools_live_model_separate_note");
    case "lost":
      return null;
  }
}

/** The model that writes a streamed recording, by name, or that none does. */
function liveModelValue(
  state: LiveModelState,
  model: TranscriptionModelLink | undefined,
  t: Translate
): string {
  if (state.kind === "picked") return modelDisplayName(state.model);
  if (state.kind === "transcription_model" && state.streams && model) {
    return modelDisplayName(model);
  }
  return t("flow_editor_tools_live_model_off");
}

/**
 * A model option's second line: its provider, which tells apart models of the
 * same name, and, among transcription models, that it is made for streaming.
 */
function modelOption(model: TranscriptionModelLink, t: Translate, showsRole: boolean) {
  const facts = [
    model.provider_name?.trim(),
    showsRole && model.supports_realtime ? t("flow_editor_tools_model_shows_live_text") : null
  ].filter(Boolean);
  return {
    value: model.id,
    label: modelDisplayName(model),
    description: facts.length > 0 ? facts.join(" · ") : undefined
  };
}

/**
 * A streaming model chosen to write files, while the space has a model made
 * for files: the one to suggest instead.
 */
function fileModelInstead(
  model: TranscriptionModelLink | undefined,
  models: readonly TranscriptionModelLink[]
): TranscriptionModelLink | undefined {
  if (!model?.supports_realtime) return undefined;
  return models.find((candidate) => !candidate.supports_realtime && candidate.can_access !== false);
}

function serviceName(service: SpeakerServiceLink, t: Translate): string {
  return service.is_default
    ? t("flow_editor_tools_speaker_service_default", { name: service.name })
    : service.name;
}

/** Who writes which audio: the routing the settings add up to. */
function TranscriptionRouting({
  settings,
  resources,
  required,
  modelMissing,
  inForm
}: {
  settings: TranscriptionSettings;
  resources: TranscriptionResources;
  required: boolean;
  modelMissing: boolean;
  /** The form shows each problem at its field, so the routing only names the outcome. */
  inForm: boolean;
}) {
  const t = useTranslations();
  const model = resources.models.find((candidate) => candidate.id === settings.modelId);
  const state = speakerServiceState(settings, resources.services, required);
  const live = liveModelState(settings, resources.models);
  const choice = settings.speakerService;
  return (
    <>
      <MetadataListItem label={t("flow_editor_tools_route_live")}>
        {live.kind === "lost" && !inForm ? (
          <span className="text-ax-warning">{t("flow_editor_tools_live_model_lost")}</span>
        ) : (
          liveModelValue(live, model, t)
        )}
      </MetadataListItem>
      <MetadataListItem label={t("flow_editor_tools_route_files")}>
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
      <MetadataListItem label={t("flow_editor_tools_speaker_service")}>
        {state.picked ? (
          state.picked.name
        ) : state.lost ? (
          <span className="text-ax-warning">
            {inForm
              ? (state.lost.name ?? t("flow_editor_tools_speaker_service_gone"))
              : lostSentence(state, required, usableSpeakerServices(resources.services).length, t)}
          </span>
        ) : choice.kind === "none" ? (
          t("flow_editor_tools_speaker_service_none")
        ) : (
          <span className="text-ax-text-secondary">
            {t("flow_editor_tools_speaker_service_unset")}
          </span>
        )}
      </MetadataListItem>
    </>
  );
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
  const state = speakerServiceState(settings, resources.services, required);
  return (
    <>
      <TranscriptionRouting
        settings={settings}
        resources={resources}
        required={required}
        modelMissing={modelMissing}
        inForm={false}
      />
      <MetadataListItem label={t("flow_editor_tools_transcription_language")}>
        {t(LANGUAGE_KEYS[settings.language])}
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
  const model = resources.models.find((candidate) => candidate.id === settings.modelId);
  const instead = fileModelInstead(model, resources.models);
  const lost = lostSentence(state, required, usable.length, t);
  const on = takesAudio || settings.enabled;
  const live = liveModelState(settings, resources.models);
  // The transcription model itself is the "same" choice, not a second option.
  const liveOptions = liveModels(resources.models).filter((model) => model.id !== settings.modelId);
  const modelStreams = liveModels(resources.models).some((model) => model.id === settings.modelId);
  const liveValue = live.kind === "transcription_model" ? UNSET : (settings.liveModelId ?? UNSET);
  // With no other streaming model, the transcription model's own role is a sentence, not a choice.
  const hasLiveSelector = liveOptions.length > 0 || live.kind !== "transcription_model";

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
    <fieldset
      data-settings-field="transcription"
      className="border-ax-border m-0 flex min-w-0 flex-col gap-4 border-t p-0 pt-5"
    >
      <legend className="float-left w-full p-0">
        <Heading level={3}>{t("flow_editor_tools_transcription_heading")}</Heading>
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
          <MetadataList orientation="horizontal">
            <TranscriptionRouting
              settings={settings}
              resources={resources}
              required={required}
              modelMissing={modelMissing}
              inForm
            />
          </MetadataList>
          <div className="grid gap-4 sm:grid-cols-2">
            <div data-settings-field="transcription_model">
              <Selector
                label={t("flow_editor_tools_transcription_model")}
                description={
                  resources.models.length === 0
                    ? t("flow_editor_tools_transcription_no_models")
                    : t("flow_editor_tools_transcription_model_description")
                }
                options={[
                  { value: NONE, label: t("flow_editor_tools_transcription_model_none") },
                  ...resources.models.map((model) => modelOption(model, t, true)),
                  ...(settings.modelId && !model
                    ? [
                        {
                          value: settings.modelId,
                          label: t("flow_editor_tools_transcription_model_gone")
                        }
                      ]
                    : [])
                ]}
                value={settings.modelId ?? NONE}
                onChange={(value) => {
                  const modelId = value === NONE ? null : value;
                  // Streaming stays with the model that did it when files move to another one.
                  const liveModelId =
                    live.kind === "transcription_model" && live.streams
                      ? settings.modelId
                      : settings.liveModelId;
                  onChange({
                    ...settings,
                    modelId,
                    liveModelId: liveModelId === modelId ? null : liveModelId
                  });
                }}
                status={
                  settings.modelId && !model
                    ? {
                        type: "warning",
                        message: t("flow_editor_tools_transcription_model_unavailable")
                      }
                    : modelMissing
                      ? {
                          type: "warning",
                          message: t("flow_editor_tools_transcription_model_missing")
                        }
                      : model && instead
                        ? {
                            type: "warning",
                            // Only a model that streams now keeps streaming after the switch.
                            message: t(
                              live.kind === "transcription_model" && live.streams
                                ? "flow_editor_tools_transcription_model_streaming"
                                : "flow_editor_tools_transcription_model_streaming_files",
                              {
                                name: modelDisplayName(model),
                                suggestion: modelDisplayName(instead)
                              }
                            )
                          }
                        : undefined
                }
                width="100%"
              />
            </div>
            {hasLiveSelector ? (
              <div data-settings-field="live_model">
                <Selector
                  label={t("flow_editor_tools_live_model")}
                  description={liveModelNote(live, t) ?? undefined}
                  options={[
                    {
                      value: UNSET,
                      label: modelStreams
                        ? t("flow_editor_tools_live_model_same")
                        : t("flow_editor_tools_live_model_off")
                    },
                    ...liveOptions.map((model) => modelOption(model, t, false)),
                    ...(live.kind === "lost"
                      ? [
                          {
                            value: liveValue,
                            label: live.model
                              ? modelDisplayName(live.model)
                              : t("flow_editor_tools_transcription_model_gone")
                          }
                        ]
                      : [])
                  ]}
                  value={liveValue}
                  onChange={(value) =>
                    onChange({ ...settings, liveModelId: value === UNSET ? null : value })
                  }
                  status={
                    live.kind === "lost"
                      ? { type: "warning", message: t("flow_editor_tools_live_model_lost") }
                      : undefined
                  }
                  width="100%"
                />
              </div>
            ) : null}
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
          {hasLiveSelector ? null : (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {live.streams
                ? t("flow_editor_tools_live_model_same_note")
                : t("flow_editor_tools_live_model_none_in_space")}
            </Text>
          )}
          {usable.length === 0 && !required && !state.lost ? (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {t("flow_editor_tools_speaker_service_none_in_space")}
            </Text>
          ) : (
            <>
              <div data-settings-field="speaker_service">
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
              </div>
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
