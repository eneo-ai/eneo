<div
  class="header-shadow header border-default bg-primary text-primary relative top-0 z-[60] ml-6 flex h-[4.25rem] min-h-[4.25rem] items-center justify-between border-b-[0.5px] pr-4"
>
  <slot />
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .header-shadow {
    box-shadow: 2rem 0.75rem 4rem 0rem rgba(0, 0, 0, 0.03);
  }
</style>
