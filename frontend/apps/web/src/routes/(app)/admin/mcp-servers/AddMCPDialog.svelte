<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Dialog, Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import type { Writable } from "svelte/store";

  type Props = {
    openController: Writable<boolean>;
    onSubmit: (data: any) => Promise<void>;
  };

  const { openController, onSubmit }: Props = $props();

  let name = $state("");
  let server_type = $state<"npm" | "uvx" | "docker" | "http">("npm");
  let description = $state("");
  let npm_package = $state("");
  let uvx_package = $state("");
  let docker_image = $state("");
  let http_url = $state("");
  let documentation_url = $state("");
  let submitting = $state(false);

  async function handleSubmit() {
    submitting = true;
    try {
      await onSubmit({
        name,
        server_type,
        description: description || undefined,
        npm_package: npm_package || undefined,
        uvx_package: uvx_package || undefined,
        docker_image: docker_image || undefined,
        http_url: http_url || undefined,
        documentation_url: documentation_url || undefined
      });
      // Reset form
      name = "";
      description = "";
      npm_package = "";
      uvx_package = "";
      docker_image = "";
      http_url = "";
      documentation_url = "";
      $openController = false;
    } finally {
      submitting = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.add_mcp_server()}</Dialog.Title>

    <Dialog.Section scrollable={true}>
      <form on:submit|preventDefault={handleSubmit} class="space-y-4 px-4 py-4">
        <div>
          <label for="name" class="text-default mb-1 block text-sm font-medium">{m.name()}</label>
          <input
            id="name"
            type="text"
            bind:value={name}
            required
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </div>

        <div>
          <label for="server_type" class="text-default mb-1 block text-sm font-medium">{m.server_type()}</label>
          <select
            id="server_type"
            bind:value={server_type}
            required
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          >
            <option value="npm">{m.npm()}</option>
            <option value="uvx">UVX</option>
            <option value="docker">{m.docker()}</option>
            <option value="http">HTTP</option>
          </select>
        </div>

        <div>
          <label for="description" class="text-default mb-1 block text-sm font-medium">{m.description()}</label>
          <textarea
            id="description"
            bind:value={description}
            rows="3"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </div>

        {#if server_type === "npm"}
          <div>
            <label for="npm_package" class="text-default mb-1 block text-sm font-medium">{m.npm_package()}</label>
            <input
              id="npm_package"
              type="text"
              bind:value={npm_package}
              placeholder="@modelcontextprotocol/server-example"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            />
          </div>
        {/if}

        {#if server_type === "uvx"}
          <div>
            <label for="uvx_package" class="text-default mb-1 block text-sm font-medium">{m.uvx_package()}</label>
            <input
              id="uvx_package"
              type="text"
              bind:value={uvx_package}
              placeholder="mcp-server-time"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            />
          </div>
        {/if}

        {#if server_type === "docker"}
          <div>
            <label for="docker_image" class="text-default mb-1 block text-sm font-medium">{m.docker_image()}</label>
            <input
              id="docker_image"
              type="text"
              bind:value={docker_image}
              placeholder="mcp/server-example:latest"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            />
          </div>
        {/if}

        {#if server_type === "http"}
          <div>
            <label for="http_url" class="text-default mb-1 block text-sm font-medium">{m.http_url()}</label>
            <input
              id="http_url"
              type="url"
              bind:value={http_url}
              placeholder="https://example.com/mcp"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            />
          </div>
        {/if}

        <div>
          <label for="documentation_url" class="text-default mb-1 block text-sm font-medium">{m.documentation_url()}</label>
          <input
            id="documentation_url"
            type="url"
            bind:value={documentation_url}
            placeholder="https://docs.example.com"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </div>
      </form>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} variant="secondary">
        {m.cancel()}
      </Button>
      <Button variant="primary" onclick={handleSubmit} disabled={submitting || !name}>
        {submitting ? m.loading() : m.add_mcp_server()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
