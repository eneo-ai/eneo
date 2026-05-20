<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button, Dialog } from "@intric/ui";
  import { type Writable } from "svelte/store";

  export type CrawlSourceValues = {
    url: string;
    crawlType: "crawl" | "sitemap";
    depth: number;
    httpAuth: { user: string; password: string } | null;
  };

  export type CrawlSourcePatch = Partial<{
    url: string;
    crawlType: "crawl" | "sitemap";
    depth: number;
    httpAuth: { user: string; password: string } | null;
  }>;

  type Initial = {
    url: string;
    crawlType: "crawl" | "sitemap";
    depth: number;
    httpAuthUser: string | null;
  };

  type Props = {
    open: Writable<boolean>;
    mode: "create" | "edit";
    initial?: Initial;
    onCreate?: (values: CrawlSourceValues) => Promise<void>;
    onPatch?: (patch: CrawlSourcePatch) => Promise<void>;
  };

  let { open, mode, initial, onCreate, onPatch }: Props = $props();

  // Form state — initialised on every dialog open from `initial` (or defaults).
  let url = $state("");
  let crawlType = $state<"crawl" | "sitemap">("crawl");
  let depth = $state(2);
  let authEnabled = $state(false);
  let authUser = $state("");
  let authPassword = $state("");
  let submitting = $state(false);
  let errorMessage = $state("");

  $effect(() => {
    if ($open) {
      // Snapshot initial values once per opening (untrack on the rest).
      url = initial?.url ?? "";
      crawlType = initial?.crawlType ?? "crawl";
      depth = initial?.depth ?? 2;
      authEnabled = !!initial?.httpAuthUser;
      authUser = initial?.httpAuthUser ?? "";
      authPassword = "";
      errorMessage = "";
      submitting = false;
    }
  });

  function validate(): string | null {
    const trimmed = url.trim();
    if (!trimmed) return "Ange en URL.";
    try {
      new URL(trimmed);
    } catch {
      return "URL:en är ogiltig.";
    }
    if (depth < 0 || depth > 10) return "Djup måste vara mellan 0 och 10.";
    if (authEnabled) {
      if (!authUser.trim()) return "Användarnamn krävs när autentisering är aktiverad.";
      if (mode === "create" && !authPassword)
        return "Lösenord krävs när autentisering är aktiverad.";
    }
    return null;
  }

  async function submit() {
    const err = validate();
    if (err) {
      errorMessage = err;
      return;
    }
    submitting = true;
    errorMessage = "";
    try {
      if (mode === "create") {
        if (!onCreate) throw new Error("missing onCreate handler");
        await onCreate({
          url: url.trim(),
          crawlType,
          depth,
          httpAuth: authEnabled ? { user: authUser.trim(), password: authPassword } : null
        });
      } else {
        if (!onPatch) throw new Error("missing onPatch handler");
        const patch: CrawlSourcePatch = {};
        if (initial) {
          if (url.trim() !== initial.url) patch.url = url.trim();
          if (crawlType !== initial.crawlType) patch.crawlType = crawlType;
          if (depth !== initial.depth) patch.depth = depth;
        }
        if (authEnabled) {
          // Password only sent if user typed one; otherwise leave existing untouched.
          if (authPassword) {
            patch.httpAuth = { user: authUser.trim(), password: authPassword };
          } else if (authUser.trim() !== (initial?.httpAuthUser ?? "")) {
            errorMessage =
              "Ange ett nytt lösenord när du ändrar användarnamnet, eller stäng av autentisering först.";
            submitting = false;
            return;
          }
        } else if (initial?.httpAuthUser) {
          // Toggle from on → off clears upstream credentials.
          patch.httpAuth = null;
        }
        await onPatch(patch);
      }
      $open = false;
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      errorMessage = e?.message ?? e?.body?.message ?? "Något gick fel.";
    } finally {
      submitting = false;
    }
  }
</script>

<Dialog.Root openController={open}>
  <Dialog.Content width="medium">
    <Dialog.Title>
      {mode === "create" ? "Lägg till crawl-källa" : "Redigera crawl-källa"}
    </Dialog.Title>
    <Dialog.Section scrollable={true}>
      <form
        onsubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        class="space-y-4 px-4 pt-2 pb-6"
      >
        {#if errorMessage}
          <div
            class="border-negative-default/30 bg-negative-dimmer text-negative-stronger rounded-lg border px-4 py-3 text-sm"
            role="alert"
          >
            {errorMessage}
          </div>
        {/if}

        <div>
          <label for="crawl-source-url" class="text-default mb-1.5 block text-sm font-medium">
            URL
            <span class="text-negative-default" aria-hidden="true">*</span>
          </label>
          <input
            id="crawl-source-url"
            type="url"
            bind:value={url}
            required
            placeholder="https://exempel.se/wiki"
            autocomplete="off"
            class="border-default bg-primary ring-accent-default focus:border-accent-default w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
          />
        </div>

        <fieldset>
          <legend class="text-default mb-1.5 block text-sm font-medium">Crawl-typ</legend>
          <div class="flex flex-col gap-2">
            <label class="flex items-start gap-2 text-sm">
              <input type="radio" bind:group={crawlType} value="crawl" class="mt-1" />
              <span>
                <span class="block font-medium">Följ länkar</span>
                <span class="text-muted block text-xs">
                  Startar på URL:en och hämtar länkade sidor till valt djup.
                </span>
              </span>
            </label>
            <label class="flex items-start gap-2 text-sm">
              <input type="radio" bind:group={crawlType} value="sitemap" class="mt-1" />
              <span>
                <span class="block font-medium">Sitemap</span>
                <span class="text-muted block text-xs">
                  URL:en behandlas som en XML-sitemap och alla listade adresser hämtas.
                </span>
              </span>
            </label>
          </div>
        </fieldset>

        {#if crawlType === "crawl"}
          <div>
            <label for="crawl-source-depth" class="text-default mb-1.5 block text-sm font-medium">
              Länkdjup (0-10)
            </label>
            <input
              id="crawl-source-depth"
              type="number"
              min="0"
              max="10"
              bind:value={depth}
              class="border-default bg-primary ring-accent-default focus:border-accent-default w-32 rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
            />
          </div>
        {/if}

        <div>
          <label class="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" bind:checked={authEnabled} />
            HTTP Basic-autentisering
          </label>
          {#if authEnabled}
            <div class="mt-2 grid grid-cols-2 gap-2">
              <input
                type="text"
                bind:value={authUser}
                placeholder="Användarnamn"
                autocomplete="off"
                class="border-default bg-primary ring-accent-default focus:border-accent-default rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
              />
              <input
                type="password"
                bind:value={authPassword}
                placeholder={mode === "edit" && initial?.httpAuthUser
                  ? "Lämna tomt för oförändrat"
                  : "Lösenord"}
                autocomplete="new-password"
                class="border-default bg-primary ring-accent-default focus:border-accent-default rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
              />
            </div>
          {/if}
        </div>
      </form>
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close} variant="outlined" disabled={submitting}>{m.cancel()}</Button>
      <Button variant="primary" onclick={submit} disabled={submitting}>
        {submitting ? m.loading() : mode === "create" ? "Skapa" : "Spara"}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
