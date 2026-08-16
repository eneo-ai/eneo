<!--
  The row height matches the space selector and the admin/account shell headers so
  the rule under it lines up across the app. Everything placed here shares this one
  row: nothing is stacked or overlaid.
-->
<div
  class="header-shadow header border-default bg-primary text-primary @container relative top-0 z-[60] ml-6 flex h-[4.25rem] min-h-[4.25rem] items-center justify-between gap-5 border-b-[0.5px] pr-4"
>
  <slot />
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .header-shadow {
    box-shadow: 2rem 0.75rem 4rem 0rem rgba(0, 0, 0, 0.03);
  }
</style>
