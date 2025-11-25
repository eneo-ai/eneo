<script lang="ts">
	import { Button, Dialog, Input } from "@intric/ui";
	import { writable, type Writable } from "svelte/store";
	import { page } from "$app/stores";
	import { invalidate } from "$app/navigation";
	import { m } from "$lib/paraglide/messages";

	export let provider: string;
	export let displayName: string | undefined = undefined;
	export let existingCredential:
		| {
				masked_key: string;
				config: Record<string, any>;
		  }
		| undefined = undefined;
	export let openController: Writable<boolean>;

	// Get field labels from translations
	function getFieldLabel(fieldName: string): string {
		if (fieldName === "api_key") return m.api_key();
		if (fieldName === "endpoint") return m.endpoint_url();
		if (fieldName === "api_version") return m.api_version();
		if (fieldName === "deployment_name") return m.deployment_name();
		return fieldName;
	}

	// Provider-specific field configurations
	const PROVIDER_FIELDS = {
		openai: [{ name: "api_key", type: "password", required: true }],
		anthropic: [{ name: "api_key", type: "password", required: true }],
		berget: [{ name: "api_key", type: "password", required: true }],
		gdm: [{ name: "api_key", type: "password", required: true }],
		mistral: [{ name: "api_key", type: "password", required: true }],
		ovhcloud: [{ name: "api_key", type: "password", required: true }],
		azure: [
			{ name: "api_key", type: "password", required: true },
			{ name: "endpoint", type: "text", required: true },
			{ name: "api_version", type: "text", required: true },
			{ name: "deployment_name", type: "text", required: true }
		],
		vllm: [
			{ name: "api_key", type: "password", required: true },
			{ name: "endpoint", type: "text", required: true }
		]
	};

	const fields =
		PROVIDER_FIELDS[provider.toLowerCase() as keyof typeof PROVIDER_FIELDS] ||
		PROVIDER_FIELDS.openai;

	// Form state
	let formData: Record<string, string> = {
		api_key: "",
		...(existingCredential?.config || {})
	};
	let isSubmitting = false;
	let errors: Record<string, string> = {};

	// Validate form
	function validateForm(): boolean {
		errors = {};
		let isValid = true;

		for (const field of fields) {
			if (field.required && !formData[field.name]?.trim()) {
				errors[field.name] = m.field_is_required({ field: getFieldLabel(field.name) });
				isValid = false;
			} else if (field.name === "api_key" && formData.api_key.length < 8) {
				errors.api_key = m.api_key_min_length();
				isValid = false;
			}
		}

		return isValid;
	}

	// Submit form
	async function handleSubmit() {
		if (!validateForm()) {
			return;
		}

		isSubmitting = true;
		const { intric } = $page.data;

		try {
			const response = await intric.credentials.set(provider.toLowerCase(), formData);
			openController.set(false);
			// Reload the page data to reflect new credentials
			await invalidate("admin:models:load");
		} catch (error: any) {
			console.error("Failed to set credentials:", error);

			// Parse validation errors if available
			if (error.status === 422 && error.response?.detail?.errors) {
				const validationErrors = error.response.detail.errors;
				if (Array.isArray(validationErrors)) {
					// Set field-level errors
					validationErrors.forEach((errorMsg: string) => {
						// Try to extract field name from error message
						// Format: "Field 'field_name' is required for provider 'provider'"
						const fieldMatch = errorMsg.match(/Field '(\w+)'/);
						if (fieldMatch) {
							errors[fieldMatch[1]] = errorMsg;
						}
					});
				}
			}
		} finally {
			isSubmitting = false;
		}
	}

	// Format provider name for display
	const displayProviderName = displayName || provider.charAt(0).toUpperCase() + provider.slice(1);
</script>

<Dialog.Root {openController}>
	<Dialog.Content width="dynamic">
		<Dialog.Title>{m.configure_provider_credentials({ provider: displayProviderName })}</Dialog.Title>

		<Dialog.Section class="space-y-4 p-4">
			{#if existingCredential}
				<div class="rounded-md bg-blue-50 p-4 text-sm text-blue-900">
					<p class="font-medium">{m.current_credential_configured()}</p>
					<p class="mt-1">{m.api_key()}: {existingCredential.masked_key}</p>
					{#if existingCredential.config.endpoint}
						<p class="mt-1">{m.endpoint()}: {existingCredential.config.endpoint}</p>
					{/if}
					<p class="mt-2 text-xs text-blue-700">
						{m.enter_new_values_to_update()}
					</p>
				</div>
			{/if}

			<form on:submit|preventDefault={handleSubmit} class="space-y-4">
				{#each fields as field}
					<div>
						<label for={field.name} class="mb-2 block text-sm font-medium text-gray-700">
							{getFieldLabel(field.name)}
							{#if field.required}
								<span class="text-red-500">*</span>
							{/if}
						</label>
						<Input.Text
							id={field.name}
							type={field.type}
							bind:value={formData[field.name]}
							placeholder={field.type === "password"
								? existingCredential
									? m.enter_new_key_to_update()
									: m.enter_api_key()
								: m.enter_field({ field: getFieldLabel(field.name).toLowerCase() })}
							disabled={isSubmitting}
							class={errors[field.name] ? "border-red-500" : ""}
						/>
						{#if errors[field.name]}
							<p class="mt-1 text-xs text-red-600">{errors[field.name]}</p>
						{/if}
					</div>
				{/each}

				<div class="rounded-md bg-gray-50 p-3 text-xs text-gray-600">
					<p>
						<strong>{m.note()}:</strong> {m.credentials_encrypted_notice()}
					</p>
				</div>
			</form>
		</Dialog.Section>

		<Dialog.Controls let:close>
			<Button is={close} variant="secondary" disabled={isSubmitting}>{m.cancel()}</Button>
			<Button on:click={handleSubmit} variant="primary" disabled={isSubmitting}>
				{isSubmitting ? m.saving() : m.save_credentials()}
			</Button>
		</Dialog.Controls>
	</Dialog.Content>
</Dialog.Root>
