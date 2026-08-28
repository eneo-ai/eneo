<div
  class="header-shadow header border-default bg-primary text-primary @container relative top-0 z-[60] ml-6 flex min-h-[4.25rem] flex-wrap items-center justify-between gap-x-5 gap-y-1 border-b-[0.5px] py-2 pr-4"
>
  <slot />
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .header-shadow {
    box-shadow: 2rem 0.75rem 4rem 0rem rgba(0, 0, 0, 0.03);
  }
</style>
