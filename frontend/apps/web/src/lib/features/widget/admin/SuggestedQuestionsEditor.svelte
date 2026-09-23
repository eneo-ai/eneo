<!--
  The suggested questions a visitor can tap before typing: one input per
  question, add with a button, remove per row. Announces changes for screen
  readers and keeps focus sensible when rows come and go.
-->
<script lang="ts">
  import { Plus, X } from "lucide-svelte";
  import { tick, untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import { collapseWhitespace } from "./textDraft.svelte";

  // Mirrors MAX_SUGGESTED_QUESTIONS in the backend's WidgetTexts.
  const MAX = 4;
  const MAX_LENGTH = 120;

  type Props = {
    questions: string[];
    onChange: (questions: string[]) => void;
    id?: string;
    /** Why the server refused the saved list. */
    error?: string;
  };

  let { questions, onChange, id = "widget-questions", error = "" }: Props = $props();

  // What the API stores for a list of rows: whitespace collapsed, blanks dropped.
  const clean = (texts: string[]) => texts.map(collapseWhitespace).filter(Boolean);

  // Rows keep their identity while editing so a cleared row does not vanish.
  let rows = $state<{ key: number; text: string }[]>([]);
  let nextKey = 0;
  let announcement = $state("");
  let seen: string | null = null;

  const focusRow = (key: number) => document.getElementById(`${id}-${key}`)?.focus();

  $effect(() => {
    // Adopt a list only when it is news: a template applied, a reload. Every
    // save answers with a fresh copy of the list just sent, which must never
    // replace rows, least of all a new row that is still being typed.
    const incoming = clean(questions).join("\n");
    untrack(() => {
      if (incoming === seen) return;
      seen = incoming;
      if (clean(rows.map((row) => row.text)).join("\n") !== incoming) {
        rows = questions.map((text) => ({ key: nextKey++, text }));
      }
    });
  });

  // The API refuses a repeated question, and the visitor's chips are keyed by it.
  const duplicates = $derived.by(() => {
    const texts = rows.map((row) => collapseWhitespace(row.text));
    return rows
      .filter((_, index) => texts[index] && texts.indexOf(texts[index]) < index)
      .map((row) => row.key);
  });

  function emit() {
    if (duplicates.length > 0) return;
    onChange(clean(rows.map((row) => row.text)));
  }

  async function add() {
    if (rows.length >= MAX) return;
    const key = nextKey++;
    rows = [...rows, { key, text: "" }];
    announcement = m.widget_admin_questions_added({ count: String(rows.length) });
    await tick();
    focusRow(key);
  }

  async function remove(index: number) {
    rows = rows.filter((_, i) => i !== index);
    emit();
    announcement = m.widget_admin_questions_removed({ count: String(rows.length) });
    await tick();
    const next = rows[Math.min(index, rows.length - 1)];
    if (next) focusRow(next.key);
    else document.getElementById(`${id}-add`)?.focus();
  }
</script>

<div class="flex flex-col gap-3">
  {#if rows.length === 0}
    <p class="text-secondary text-sm">{m.widget_admin_questions_empty_hint()}</p>
  {/if}
  <ol class="flex flex-col gap-2" aria-label={m.widget_admin_text_suggestions()}>
    {#each rows as row, index (row.key)}
      {@const duplicate = duplicates.includes(row.key)}
      <li class="flex items-center gap-2">
        <Field.Field class="flex-1" data-invalid={duplicate || undefined}>
          <Field.Label for={`${id}-${row.key}`} class="sr-only">
            {m.widget_admin_questions_label({ index: String(index + 1) })}
          </Field.Label>
          <Input
            id={`${id}-${row.key}`}
            bind:value={row.text}
            maxlength={MAX_LENGTH}
            placeholder={m.widget_admin_questions_placeholder()}
            aria-invalid={duplicate}
            aria-describedby={duplicate ? `${id}-${row.key}-error` : undefined}
            onblur={emit}
            onkeydown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                emit();
                if (index === rows.length - 1) void add();
              }
            }}
          />
          {#if duplicate}
            <Field.Error id={`${id}-${row.key}-error`}
              >{m.widget_admin_questions_duplicate()}</Field.Error
            >
          {/if}
        </Field.Field>
        <Button
          variant="ghost"
          size="icon"
          aria-label={m.widget_admin_questions_remove({ index: String(index + 1) })}
          onclick={() => remove(index)}
        >
          <X aria-hidden="true" />
        </Button>
      </li>
    {/each}
  </ol>
  {#if error}
    <Field.Error id={`${id}-error`}>{error}</Field.Error>
  {/if}
  <div class="flex items-center justify-between gap-3">
    <Button
      id={`${id}-add`}
      variant="outline"
      size="sm"
      onclick={add}
      disabled={rows.length >= MAX}
    >
      <Plus aria-hidden="true" data-icon="inline-start" />
      {m.widget_admin_questions_add()}
    </Button>
    <span class="text-secondary text-xs">
      {m.widget_admin_questions_limit({ count: String(rows.length), max: String(MAX) })}
    </span>
  </div>
  <div class="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
</div>
