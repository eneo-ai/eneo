<script lang="ts">
  let { text = "" }: { text?: string } = $props();
</script>

<span class="inline-chip">{text}</span>

<style>
  .inline-chip {
    display: inline;
    margin-left: 0.125rem;
  }
</style>
