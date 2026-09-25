<!--
  Search, membership and "Visa" for the list of spaces. Everything filters on
  the client as you type or choose; the page announces the new count.
-->
<script lang="ts">
  import { Check, X } from "@lucide/svelte";
  import { RadioGroup as RadioGroupPrimitive } from "bits-ui";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import {
    MEMBERSHIP_FILTERS,
    SHOW_FILTERS,
    type MembershipFilter,
    type ShowFilter,
    type SpaceListQuery
  } from "./space-list-query";

  type Props = {
    query: SpaceListQuery;
    counts: Record<MembershipFilter, number>;
    filtered: boolean;
    onChange: (change: Partial<SpaceListQuery>) => void;
    onClear: () => void;
    /** The search field, so the page can put focus back after clearing. */
    searchInput?: HTMLInputElement | null;
  };

  let {
    query,
    counts,
    filtered,
    onChange,
    onClear,
    searchInput = $bindable(null)
  }: Props = $props();

  const number = new Intl.NumberFormat(intlLocale());

  function membershipLabel(option: MembershipFilter) {
    const count = number.format(counts[option]);
    switch (option) {
      case "all":
        return m.admin_spaces_membership_all({ count });
      case "member":
        return m.admin_spaces_membership_member({ count });
      case "not_member":
        return m.admin_spaces_membership_not_member({ count });
      default:
        return option satisfies never;
    }
  }

  function showLabel(option: ShowFilter) {
    switch (option) {
      case "all":
        return m.admin_spaces_show_all();
      case "attention":
        return m.admin_spaces_show_attention();
      case "no_admin":
        return m.admin_spaces_show_no_admin();
      case "widget_request":
        return m.admin_spaces_show_widget_request();
      default:
        return option satisfies never;
    }
  }
</script>

<form
  role="search"
  aria-label={m.admin_spaces_filters_label()}
  class="border-default bg-primary flex flex-col gap-4 rounded-lg border p-4"
  onsubmit={(event) => event.preventDefault()}
>
  <div class="grid gap-4 @3xl:grid-cols-[minmax(0,28rem)_minmax(12rem,16rem)]">
    <div class="flex min-w-0 flex-col gap-2">
      <Label for="spaces-search">{m.admin_spaces_search_label()}</Label>
      <Input
        id="spaces-search"
        type="search"
        autocomplete="off"
        bind:ref={searchInput}
        value={query.q}
        aria-describedby="spaces-search-hint"
        class="max-md:min-h-12"
        oninput={(event) => onChange({ q: event.currentTarget.value })}
      />
      <p id="spaces-search-hint" class="text-secondary text-sm">{m.admin_spaces_search_hint()}</p>
    </div>
    <div class="flex min-w-0 flex-col gap-2">
      <Label id="spaces-show-label" for="spaces-show">{m.show()}</Label>
      <Select.Root
        type="single"
        value={query.show}
        onValueChange={(value) => onChange({ show: value as ShowFilter })}
      >
        <!-- Named by the label and its value, so the choice is read out with it. -->
        <Select.Trigger
          id="spaces-show"
          aria-labelledby="spaces-show-label spaces-show-value"
          class="w-full max-md:min-h-12"
        >
          <span id="spaces-show-value" class="truncate">{showLabel(query.show)}</span>
        </Select.Trigger>
        <Select.Content>
          {#each SHOW_FILTERS as option (option)}
            <Select.Item value={option} label={showLabel(option)}>{showLabel(option)}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </div>
  </div>

  <div class="flex flex-wrap items-end justify-between gap-4">
    <fieldset class="flex w-full min-w-0 flex-col gap-2 @2xl:w-auto">
      <legend id="spaces-membership-legend" class="mb-2 text-sm font-medium">
        {m.admin_spaces_membership_legend()}
      </legend>
      <RadioGroupPrimitive.Root
        value={query.membership}
        onValueChange={(value) => onChange({ membership: value as MembershipFilter })}
        aria-labelledby="spaces-membership-legend"
        orientation="horizontal"
        class="bg-secondary flex flex-col gap-1 rounded-lg p-1 @2xl:flex-row @2xl:flex-wrap"
      >
        {#each MEMBERSHIP_FILTERS as option (option)}
          <!-- The choice shows by a 3:1 border and a check mark, not by colour alone. -->
          <RadioGroupPrimitive.Item
            value={option}
            class="text-secondary hover:text-primary data-[state=checked]:border-muted-foreground data-[state=checked]:bg-primary data-[state=checked]:text-primary focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded-md border border-transparent px-3 py-1.5 text-left text-sm font-medium outline-none focus-visible:ring-3 data-[state=checked]:shadow-sm max-md:min-h-12"
          >
            {#snippet children({ checked })}
              {#if checked}
                <Check class="size-4 shrink-0" aria-hidden="true" />
              {/if}
              {membershipLabel(option)}
            {/snippet}
          </RadioGroupPrimitive.Item>
        {/each}
      </RadioGroupPrimitive.Root>
    </fieldset>
    {#if filtered}
      <Button variant="ghost" class="max-md:min-h-12" onclick={onClear}>
        <X aria-hidden="true" data-icon="inline-start" />
        {m.admin_spaces_clear_filters()}
      </Button>
    {/if}
  </div>
</form>
