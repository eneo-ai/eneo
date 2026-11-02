import { Banner } from "@astryxdesign/core/Banner";
import { Switch } from "@astryxdesign/core/Switch";
import { useTranslations } from "use-intl";
import type { TranscriptionServiceSummary } from "@/features/admin/models/transcription-services";
import type { Space } from "@/features/spaces/space";

type Link = NonNullable<Space["transcription_services"]>[number];

/**
 * The organisation's speaker identification services, each a switch that
 * grants it to the space. A granted service that cannot be used says why and
 * can still be removed; one that is turned off or below the space's
 * classification cannot be added. Each switch saves the whole list, so the
 * owner takes one change at a time (`savingId`) and builds it from the space
 * the latest save returned.
 */
export function SpaceSpeakerServices({
  services,
  links,
  spaceClassification,
  securityEnabled,
  canEdit,
  savingId,
  onToggle
}: {
  /** The organisation's catalogue, as space editors see it. */
  services: TranscriptionServiceSummary[];
  /**
   * Every granted service, usable or not. Undefined when the space came
   * without them: a save would then drop grants it cannot see, so none is offered.
   */
  links: Link[] | undefined;
  spaceClassification: Space["security_classification"];
  /** Without security classifications every service meets the space's. */
  securityEnabled: boolean;
  canEdit: boolean;
  /** The service whose change is saving, if any. */
  savingId: string | null;
  onToggle: (service: TranscriptionServiceSummary, grant: boolean) => void;
}) {
  const t = useTranslations();

  if (links === undefined) {
    return <Banner role="alert" status="error" title={t("speaker_service_space_load_failed")} />;
  }
  if (services.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("speaker_service_empty_title")}</p>;
  }

  // The backend's rule: below a classified space only a service classified at
  // least as high may be granted.
  function meetsClassification(service: TranscriptionServiceSummary): boolean {
    if (!securityEnabled || !spaceClassification) return true;
    const own = service.security_classification;
    return own !== null && own.security_level >= spaceClassification.security_level;
  }

  function blockedReason(service: TranscriptionServiceSummary, link: Link | undefined) {
    const meets = link ? link.meets_security_classification : meetsClassification(service);
    const available = link ? link.available : service.is_enabled;
    if (!meets) return t("speaker_service_reason_classification");
    if (!available) return t("speaker_service_reason_disabled");
    return undefined;
  }

  return (
    <ul className="border-ax-border rounded-ax-container divide-ax-border divide-y border">
      {services.map((service) => {
        const link = links.find((granted) => granted.id === service.id);
        const granted = link !== undefined;
        const reason = blockedReason(service, link);
        // The organisation's default fills in flows only where the space has it.
        const note =
          reason ??
          (service.is_default
            ? granted
              ? t("speaker_service_space_default")
              : t("speaker_service_space_default_not_granted")
            : undefined);
        const blocked = !canEdit
          ? t("tools_readiness_permission")
          : !granted && reason !== undefined
            ? reason
            : undefined;
        return (
          <li key={service.id} className="px-4 py-3">
            {/* Bound to the grant itself, so a failed save never leaves the
                switch showing a state the space does not have. The list is
                sent whole, so while one change saves (its switch busy and
                keeping focus) a press on any switch is ignored. */}
            <Switch
              label={service.name}
              description={note}
              labelPosition="start"
              labelSpacing="spread"
              width="100%"
              value={granted}
              isDisabled={blocked !== undefined}
              disabledMessage={blocked}
              isLoading={savingId === service.id}
              onChange={(next) => {
                if (savingId === null && blocked === undefined) onToggle(service, next);
              }}
            />
          </li>
        );
      })}
    </ul>
  );
}
