<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Grants the organisation's speaker identification services to the space, with
  the interaction and save path of SelectSpaceModels: each switch saves the
  whole list, built from the space the latest update returned, one save at a
  time. A granted service that cannot be used says why and can still be
  removed; one that is turned off or below the space's classification cannot be
  added.
-->

<script lang="ts">
  import type { TranscriptionServiceSummary } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { toastError } from "$lib/core/errors";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** The organisation's catalogue, as space editors see it. */
    services: TranscriptionServiceSummary[];
    /** Without security classifications every service meets the space's. */
    securityEnabled: boolean;
  };

  const { services, securityEnabled }: Props = $props();

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();
  const uid = $props.id();

  // Every granted service, usable or not. Null when the space came without
  // them: a save would then drop grants it cannot see, so none is offered.
  const links = $derived($currentSpace.transcription_services ?? null);
  // Each save sends the whole list, so a second switch waits for the first.
  let saving = $state(false);

  // The backend's rule: below a classified space only a service classified at
  // least as high may be granted.
  function meetsClassification(service: TranscriptionServiceSummary): boolean {
    const required = $currentSpace.security_classification;
    if (!securityEnabled || !required) return true;
    const own = service.security_classification;
    return own !== null && own.security_level >= required.security_level;
  }

  function blockedReason(service: TranscriptionServiceSummary): string | undefined {
    const link = links?.find((granted) => granted.id === service.id);
    const meets = link ? link.meets_security_classification : meetsClassification(service);
    const available = link ? link.available : service.is_enabled;
    if (!meets) return m.speaker_service_reason_classification();
    if (!available) return m.speaker_service_reason_disabled();
    return undefined;
  }

  async function toggle(service: TranscriptionServiceSummary) {
    if (saving || links === null) return;
    saving = true;
    const adding = !links.some((granted) => granted.id === service.id);
    try {
      await updateSpace((latest) => {
        const current = latest.transcription_services;
        if (!current) throw new Error(m.speaker_service_space_load_failed());
        const ids = current.map((granted) => granted.id).filter((id) => id !== service.id);
        return {
          transcription_services: (adding ? [...ids, service.id] : ids).map((id) => ({ id }))
        };
      });
    } catch (error) {
      toastError(error);
    } finally {
      saving = false;
    }
  }
</script>

<Settings.Row
  title={m.speaker_identification()}
  description={m.speaker_service_space_description()}
>
  {#if links === null}
    <p role="alert" class="text-negative-default text-sm">
      {m.speaker_service_space_load_failed()}
    </p>
  {:else if services.length === 0}
    <p class="text-muted-foreground text-sm">{m.speaker_service_empty_title()}</p>
  {:else}
    <div class="border-default overflow-hidden rounded-xl border">
      {#each services as service (service.id)}
        {@const granted = links.some((link) => link.id === service.id)}
        {@const reason = blockedReason(service)}
        <Field.Field
          orientation="horizontal"
          class="border-default border-b px-4 py-3 last:border-b-0"
        >
          <Field.Content>
            <Field.Label for="{uid}-{service.id}">{service.name}</Field.Label>
            {#if reason}
              <Field.Description id="{uid}-{service.id}-reason">{reason}</Field.Description>
            {/if}
          </Field.Content>
          <Switch
            id="{uid}-{service.id}"
            checked={granted}
            disabled={saving || (!granted && reason !== undefined)}
            onCheckedChange={() => toggle(service)}
            aria-describedby={reason ? `${uid}-${service.id}-reason` : undefined}
          />
        </Field.Field>
      {/each}
    </div>
  {/if}
</Settings.Row>
