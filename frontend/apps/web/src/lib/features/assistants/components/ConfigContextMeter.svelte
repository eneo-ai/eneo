<script lang="ts">
  import { AlertTriangle } from "lucide-svelte";
  import ContextMeterFill from "$lib/components/ContextMeterFill.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  type Model = { id: string; max_input_tokens: number };
  type Props = {
    assistantId: string;
    model: Model | undefined;
    prompt: string;
    attachments: { id: string }[];
  };
  const { assistantId, model, prompt, attachments }: Props = $props();

  const eneo = getEneo();

  // used = system prompt + attachments — the context every question starts with.
  let used = $state(0);
  let reserve = $state(0);
  let loaded = $state(false);
  // Generation counter drops stale responses when the model/attachments change
  // mid-flight (mirrors ChatService's preflight debounce).
  let gen = 0;
  let debounce: ReturnType<typeof setTimeout> | null = null;

  const limit = $derived(model?.max_input_tokens ?? 0);
  // Prompt + attachments must fit below the window minus a reserve for the live
  // question; past the ceiling the save is rejected, so warn (amber) as it nears.
  const ceiling = $derived(Math.max(limit - reserve, 0));
  const percent = $derived(limit > 0 ? (used / limit) * 100 : 0);
  const show = $derived(loaded && limit > 0 && used > 0);
  const tone = $derived(
    ceiling > 0 && used > ceiling ? "over" : ceiling > 0 && used > ceiling * 0.8 ? "near" : "ok"
  );

  const nf = $derived(new Intl.NumberFormat(getLocale() === "sv" ? "sv-SE" : "en-US"));

  $effect(() => {
    // Read model, prompt and attachments synchronously so Svelte re-runs this
    // whenever any of them changes (the async preflight below is not tracked).
    // The denominator uses the LIVE picked model (see parent), so it stays
    // correct before saving.
    const modelId = model?.id;
    const promptText = prompt ?? "";
    const fileIds = attachments.map((a) => ({ id: a.id }));
    // The ceiling covers prompt + attachments, so meter as soon as either has
    // content: a prompt that alone overflows is surfaced even with no files.
    const hasContent = fileIds.length > 0 || promptText.trim().length > 0;

    if (debounce) clearTimeout(debounce);

    if (!modelId || !hasContent) {
      loaded = false;
      used = 0;
      return;
    }

    const current = ++gen;
    debounce = setTimeout(async () => {
      try {
        const res = await eneo.conversations.preflight({
          chatPartner: { id: assistantId, type: "assistant" },
          question: "",
          files: fileIds,
          assistantPrompt: promptText
        });
        if (current !== gen) return;
        used = res.file_tokens + (res.prompt_tokens ?? 0);
        reserve = res.context_reserve_tokens ?? 0;
        loaded = true;
      } catch {
        // Advisory only — hide on failure rather than block editing.
        if (current !== gen) return;
        loaded = false;
        used = 0;
      }
    }, 400);

    return () => {
      if (debounce) clearTimeout(debounce);
    };
  });

  const barClass = $derived(
    tone === "over"
      ? "bg-negative-stronger"
      : tone === "near"
        ? "bg-warning-stronger"
        : "bg-accent-stronger"
  );
  const textClass = $derived(
    tone === "over"
      ? "text-negative-stronger"
      : tone === "near"
        ? "text-warning-stronger"
        : "text-secondary"
  );
</script>

{#if show}
  <div class="border-default flex flex-col gap-1.5 border-b px-4 py-3">
    <div class="flex items-center justify-between gap-3">
      <span class="text-default text-sm font-medium">{m.config_attachment_meter_label()}</span>
      <span class="text-sm tabular-nums {textClass}">
        {m.config_attachment_meter_summary({
          used: nf.format(used),
          limit: nf.format(limit),
          percent: percent.toFixed(percent >= 10 ? 0 : 1)
        })}
      </span>
    </div>
    <div
      class="bg-tertiary border-dimmer relative h-2.5 w-full overflow-hidden rounded-full border"
      role="progressbar"
      aria-valuenow={used}
      aria-valuemin="0"
      aria-valuemax={limit}
      aria-label={m.config_attachment_meter_aria()}
    >
      <ContextMeterFill widthPct={Math.min(percent, 100)} class={barClass} />
    </div>
    {#if tone === "over"}
      <p
        class="text-negative-stronger flex items-start gap-1.5 text-xs leading-snug"
        role="status"
        aria-live="polite"
      >
        <AlertTriangle class="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
        {m.config_attachment_meter_over_budget()}
      </p>
    {/if}
  </div>
{/if}
