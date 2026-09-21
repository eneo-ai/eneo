<script lang="ts">
  import { AlertCircle, RefreshCw } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils";

  let {
    message,
    loading = false,
    onretry
  }: {
    message: string;
    loading?: boolean;
    onretry: () => void | Promise<void>;
  } = $props();
</script>

<Alert.Root class="border-default">
  <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
    <div class="flex min-w-0 items-start gap-2">
      <AlertCircle class="text-negative-default mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <Alert.Description>{message}</Alert.Description>
    </div>
    <Button
      variant="outline"
      class="self-start sm:self-auto"
      disabled={loading}
      aria-busy={loading}
      onclick={onretry}
    >
      <RefreshCw data-icon="inline-start" class={cn(loading && "motion-safe:animate-spin")} />
      {m.retry()}
    </Button>
  </div>
</Alert.Root>
