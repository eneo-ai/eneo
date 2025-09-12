<script lang="ts">
  export let primary: string;
  export let secondary: string | undefined = undefined;
</script>

<div>
  <p class="text-primary font-medium">{primary}</p>
  {#if secondary}
    <p class="text-muted text-sm">{secondary}</p>
  {/if}
</div>
