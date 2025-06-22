<script>
  import { IconProfile } from "@intric/icons/profile";
  import { IconAssistant } from "@intric/icons/assistant";
  import { IconKey } from "@intric/icons/key";
  import { IconLogout } from "@intric/icons/logout";
  import { Button } from "@intric/ui";
  import { createDropdownMenu } from "@melt-ui/svelte";
  import { fly, fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import SelectLanguage from "$lib/components/SelectLanguage.svelte";

  const {
    elements: { menu, item, trigger, overlay, arrow },
    states: { open }
  } = createDropdownMenu({
    positioning: {
      fitViewport: true,
      flip: true,
      placement: "bottom",
      overflowPadding: 16
    },
    forceVisible: true,
    loop: true,
    preventScroll: false,
    arrowSize: 12
  });
</script>

<Button
  is={[$trigger]}
  unstyled
  label={m.account_and_settings()}
  class="text-secondary hover:bg-accent-dimmer hover:text-brand-intric relative flex h-[3.25rem] !min-w-[3.5rem] items-center justify-center"
>
  <IconProfile class="!h-7 !min-w-7 !stroke-[1.4]" />
</Button>
{#if $open}
  <div
    {...$overlay}
    use:overlay
    class="bg-overlay-dimmer fixed inset-0 z-[40]"
    transition:fade={{ duration: 200 }}
  ></div>
  <div
    {...$menu}
    use:menu
    in:fly={{ y: -15, duration: 100 }}
    out:fly={{ y: -5, duration: 200 }}
    class="items border-stronger bg-primary absolute z-[50] flex min-w-[15rem] -translate-y-[0.75rem] flex-col rounded-sm border-b p-3 shadow-md"
  >
    <p
      class="border-default text-secondary border-b px-6 pt-1 pb-2.5 font-mono text-[0.85rem] font-medium tracking-[0.015rem]"
    >
      {m.settings()}
    </p>
    <Button
      unstyled
      is={[$item]}
      href="/account"
      padding="icon-leading"
      class="group border-default text-primary hover:bg-accent-dimmer hover:text-accent-stronger relative flex h-[3.5rem] w-full items-center justify-start gap-3 border-b pr-4 pl-5 last-of-type:border-b-0"
    >
      <IconAssistant />
      {m.my_account()}</Button
    ><Button
      is={[$item]}
      unstyled
      href="/account/api-keys"
      padding="icon-leading"
      class="group border-default text-primary hover:bg-accent-dimmer hover:text-accent-stronger relative flex h-[3.5rem] w-full items-center justify-start gap-3 border-b pr-4 pl-5 last-of-type:border-b-0"
    >
      <IconKey />
      {m.my_api_keys()}</Button
    >
    <Button
      variant="destructive"
      is={[$item]}
      href="/logout"
      class="mt-3 flex !justify-center !gap-2 rounded-lg !py-2 focus:ring-offset-4 focus:outline-offset-4"
    >
      <IconLogout />
      {m.logout()}</Button
    >

    <div {...$arrow} use:arrow class="border-stronger !z-10"></div>
  </div>
{/if}

<style>
  .items {
    box-shadow:
      0px 10px 20px -10px rgba(0, 0, 0, 0.5),
      0px 30px 50px 0px rgba(0, 0, 0, 0.2);
  }
</style>
