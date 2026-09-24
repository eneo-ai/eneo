<script lang="ts">
  let { label = "" }: { label?: string } = $props();
</script>

<div class="shadow-card">{label}</div>

<style>
  .shadow-card {
    border-radius: 0.5rem;
    padding: 1rem;
  }
</style>
