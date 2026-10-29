<!--
  The persona a widget or template answers with: a name, an uploaded avatar
  and whether that avatar is the launcher button on the host page. Shared by
  the widget editor and the template page; the caller saves the change.

  The avatar id is public and only the editor's own uploads are accepted by
  the API, so "use the assistant's icon" copies the image into a new upload
  instead of sharing the id. Removing an avatar only clears the reference:
  the server deletes the image once nothing shows it.
-->
<script lang="ts">
  import type { WidgetPersona } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import IconUpload from "$lib/features/icons/IconUpload.svelte";
  import { m } from "$lib/paraglide/messages";
  import { monogram } from "../persona";
  import WidgetPersonaByline from "../components/WidgetPersonaByline.svelte";
  import { collapseWhitespace, TextDraft } from "./textDraft.svelte";

  type Props = {
    persona: WidgetPersona;
    /** The chat's title, to warn when the persona repeats it. */
    title?: string;
    /** The assistant behind the widget, whose icon can be copied. */
    assistantIconId?: string | null;
    locked?: boolean;
    lockHint?: string;
    idPrefix?: string;
    errors?: Record<string, string>;
    onChange: (persona: WidgetPersona) => void;
  };

  let {
    persona,
    title = "",
    assistantIconId = null,
    locked = false,
    lockHint = "",
    idPrefix = "widget",
    errors = {},
    onChange
  }: Props = $props();

  const eneo = getEneo();
  const id = (name: string) => `${idPrefix}-persona-${name}`;
  const lockRef = $derived(locked ? id("lock") : "");

  // The name is typed; the API echoes it cleaned, so the draft keeps the
  // editor's spacing while they type (see TextDraft).
  const name = new TextDraft(() => persona.name ?? "");
  // A monogram is the first character, so it must be a letter; the API
  // refuses anything else, and the field says so before a save is tried.
  const nameInvalid = $derived(
    !!collapseWhitespace(name.text) && !/^\p{L}/u.test(name.text.trim())
  );
  const nameProblem = $derived(
    nameInvalid ? m.widget_admin_persona_name_invalid() : errors["name"]
  );
  const repeatsTitle = $derived(
    !!collapseWhitespace(name.text) &&
      collapseWhitespace(name.text).toLocaleLowerCase() ===
        collapseWhitespace(title).toLocaleLowerCase()
  );
  const savedName = $derived(persona.name ?? "");
  const hasName = $derived(savedName.length > 0);
  const avatarUrl = $derived(
    persona.avatar_icon_id ? eneo.icons.url({ id: persona.avatar_icon_id }) : null
  );

  function setName(value: string) {
    name.text = value;
    if (nameInvalid) return;
    const cleaned = collapseWhitespace(value);
    if (cleaned === persona.name) return;
    // No name, no face: the API refuses an avatar on an empty persona.
    onChange(
      cleaned
        ? { ...persona, name: cleaned }
        : { ...persona, name: "", avatar_icon_id: null, avatar_in_launcher: false }
    );
  }

  let uploading = $state(false);
  let uploadError = $state<string | null>(null);

  async function upload(file: File) {
    uploading = true;
    uploadError = null;
    try {
      const uploaded = await eneo.icons.upload({ file });
      onChange({ ...persona, avatar_icon_id: uploaded.id });
    } catch (error) {
      console.error("Failed to upload the persona avatar:", error);
      uploadError = m.avatar_upload_failed();
    } finally {
      uploading = false;
    }
  }

  function remove() {
    uploadError = null;
    onChange({ ...persona, avatar_icon_id: null, avatar_in_launcher: false });
  }

  async function copyAssistantIcon() {
    if (!assistantIconId) return;
    uploading = true;
    uploadError = null;
    try {
      const response = await fetch(eneo.icons.url({ id: assistantIconId }));
      if (!response.ok) throw new Error(`Icon fetch returned ${response.status}`);
      const blob = await response.blob();
      const uploaded = await eneo.icons.upload({
        file: new File([blob], "avatar", { type: blob.type })
      });
      onChange({ ...persona, avatar_icon_id: uploaded.id });
    } catch (error) {
      console.error("Failed to copy the assistant's icon:", error);
      uploadError = m.widget_admin_persona_use_assistant_icon_failed();
    } finally {
      uploading = false;
    }
  }

  const preview = $derived(
    hasName
      ? {
          name: savedName,
          avatarUrl,
          monogram: monogram(savedName),
          inLauncher: persona.avatar_in_launcher ?? false
        }
      : null
  );
</script>

<Field.Group class="grid gap-6">
  {#if locked}
    <Field.Description id={id("lock")}>{lockHint}</Field.Description>
  {/if}

  <Field.Field data-invalid={nameProblem ? true : undefined}>
    <Field.Label for={id("name")}>{m.widget_admin_persona_name()}</Field.Label>
    <Input
      id={id("name")}
      maxlength={30}
      value={name.text}
      disabled={locked}
      aria-invalid={!!nameProblem}
      aria-describedby={[
        id("name-help"),
        nameProblem ? id("name-error") : "",
        repeatsTitle ? id("name-title") : "",
        lockRef
      ]
        .filter(Boolean)
        .join(" ")}
      onfocus={name.focus}
      onblur={name.blur}
      oninput={(event) => setName(event.currentTarget.value)}
    />
    <Field.Description id={id("name-help")}
      >{m.widget_admin_persona_name_description()}</Field.Description
    >
    {#if repeatsTitle}
      <Field.Description id={id("name-title")} class="text-warning-stronger"
        >{m.widget_admin_persona_name_same_as_title()}</Field.Description
      >
    {/if}
    {#if nameProblem}
      <Field.Error id={id("name-error")}>{nameProblem}</Field.Error>
    {/if}
  </Field.Field>

  <Field.Set>
    <Field.Legend>{m.widget_admin_persona_avatar()}</Field.Legend>
    <Field.Description id={id("avatar-help")}
      >{m.widget_admin_persona_avatar_description()}</Field.Description
    >
    {#if !hasName}
      <Field.Description id={id("avatar-needs-name")}
        >{m.widget_admin_persona_avatar_needs_name()}</Field.Description
      >
    {:else if locked}
      {#if avatarUrl}
        <img
          class="size-16 rounded-full object-cover"
          src={avatarUrl}
          alt=""
          width="64"
          height="64"
        />
      {/if}
    {:else}
      <div class="flex flex-col gap-2">
        <IconUpload
          iconUrl={avatarUrl}
          {uploading}
          error={uploadError}
          inputId={id("avatar-input")}
          removeLabel={m.widget_admin_persona_remove_avatar()}
          on:upload={(event) => void upload(event.detail)}
          on:delete={remove}
        />
        {#if assistantIconId && !uploading}
          <div class="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onclick={() => void copyAssistantIcon()}
              >{m.widget_admin_persona_use_assistant_icon()}</Button
            >
            <span class="text-secondary text-xs"
              >{m.widget_admin_persona_use_assistant_icon_description()}</span
            >
          </div>
        {/if}
      </div>
      {#if errors["avatar_icon_id"]}
        <Field.Error>{errors["avatar_icon_id"]}</Field.Error>
      {/if}
    {/if}
  </Field.Set>

  {#if persona.avatar_icon_id}
    <Field.Field orientation="horizontal">
      <Field.Content>
        <Field.Label for={id("in-launcher")}>{m.widget_admin_persona_in_launcher()}</Field.Label>
        <Field.Description id={id("in-launcher-help")}
          >{m.widget_admin_persona_in_launcher_description()}</Field.Description
        >
      </Field.Content>
      <Switch
        id={id("in-launcher")}
        checked={persona.avatar_in_launcher ?? false}
        disabled={locked}
        aria-describedby={[id("in-launcher-help"), lockRef].filter(Boolean).join(" ")}
        onCheckedChange={(checked) => onChange({ ...persona, avatar_in_launcher: checked })}
      />
    </Field.Field>
  {/if}

  {#if preview}
    <div class="border-default flex flex-col gap-3 rounded-lg border p-4" aria-live="polite">
      <p class="text-secondary text-xs">{m.widget_admin_persona_preview()}</p>
      <WidgetPersonaByline persona={preview} />
    </div>
  {/if}
</Field.Group>
