<!--
  The "Webbwidget" page body: status and lifecycle on top, the autosaved
  settings on the left, the live preview, snippet and in-app test on the right.
-->
<script lang="ts">
  import type { Assistant, Eneo, Widget, WidgetPolicy } from "@eneo/eneo-js";
  import { beforeNavigate } from "$app/navigation";
  import { page } from "$app/state";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import type { LoaderRelease } from "./snippet";
  import { WidgetAutosave } from "./widgetAutosave.svelte";
  import WidgetLiveTest from "./WidgetLiveTest.svelte";
  import WidgetPreview from "./WidgetPreview.svelte";
  import WidgetSettingsForm from "./WidgetSettingsForm.svelte";
  import WidgetSnippet from "./WidgetSnippet.svelte";
  import WidgetStatusBar from "./WidgetStatusBar.svelte";
  import WidgetUsage from "./WidgetUsage.svelte";

  type Props = {
    widget: Widget;
    assistant: Assistant;
    eneo: Eneo;
    isAdmin: boolean;
    policy: WidgetPolicy | null;
    release: LoaderRelease | null;
  };

  let { widget, assistant, eneo, isAdmin, policy, release }: Props = $props();

  const autosave = untrack(
    () =>
      new WidgetAutosave(widget, async (update) => {
        try {
          return await eneo.widgets.update({ widget: { id: widget.id }, update });
        } catch (error) {
          toastError(error, m.widget_admin_save_failed());
          throw error;
        }
      })
  );

  beforeNavigate(() => {
    void autosave.flush();
  });

  const lifecycle = (action: (params: { id: string }) => Promise<Widget>) => async () => {
    autosave.replace(await action({ id: widget.id }));
  };
</script>

<div class="flex flex-col gap-6">
  <WidgetStatusBar
    {autosave}
    {isAdmin}
    onActivate={lifecycle(eneo.widgets.activate)}
    onPause={lifecycle(eneo.widgets.pause)}
    onArchive={lifecycle(eneo.widgets.archive)}
  />

  <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
    <div class="flex min-w-0 flex-col gap-6">
      <WidgetSettingsForm {autosave} {policy} assistantPublished={assistant.published ?? false} />
      <WidgetUsage widget={autosave.widget} {eneo} />
    </div>
    <aside class="flex min-w-0 flex-col gap-4 self-start xl:sticky xl:top-4">
      <WidgetPreview widget={autosave.widget} {eneo} />
      <WidgetSnippet widget={autosave.widget} {release} origin={page.url.origin} />
      <WidgetLiveTest widget={autosave.widget} {eneo} />
    </aside>
  </div>
</div>
