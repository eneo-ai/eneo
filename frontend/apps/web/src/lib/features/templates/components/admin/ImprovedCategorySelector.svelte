<script lang="ts">
	import { createSelect } from '@melt-ui/svelte';
	import { IconChevronDown } from '@intric/icons/chevron-down';
	import { IconCheck } from '@intric/icons/check';
	import { Input } from '@intric/ui';
	import { m } from '$lib/paraglide/messages';
	import {
		assistantTemplateCategories,
		appTemplateCategories,
		formatCategoryTitle
	} from '../../TemplateCategories';
	import { fade } from 'svelte/transition';

	interface Props {
		value?: string;
		type: 'assistant' | 'app';
	}

	let { value = $bindable(''), type }: Props = $props();

	const predefinedCategories =
		type === 'assistant' ? assistantTemplateCategories : appTemplateCategories;
	const categoryKeys = Object.keys(predefinedCategories);

	// Mode: 'predefined' or 'custom'
	let mode = $state<'predefined' | 'custom'>('predefined');
	let customValue = $state('');
	let predefinedValue = $state(categoryKeys[0] || '');

	// Ensure initial value is set for predefined mode
	$effect(() => {
		if (mode === 'predefined' && !value && predefinedValue) {
			value = predefinedValue;
		}
	});

	// Initialize mode and values based on incoming value
	$effect(() => {
		if (value) {
			if (categoryKeys.includes(value)) {
				mode = 'predefined';
				predefinedValue = value;
			} else {
				mode = 'custom';
				customValue = value;
			}
		}
	});

	// Update external value when mode or internal values change
	$effect(() => {
		if (mode === 'predefined') {
			value = predefinedValue;
		} else {
			value = customValue;
		}
	});

	const {
		elements: { trigger, menu, option },
		helpers: { isSelected },
		states: { open }
	} = createSelect<string>({
		defaultSelected: { value: predefinedValue },
		positioning: {
			placement: 'bottom',
			strategy: 'fixed',
			fitViewport: true,
			sameWidth: true
		},
		portal: 'body',
		onSelectedChange: ({ next }) => {
			if (next?.value) {
				predefinedValue = next.value;
			}
			return next;
		}
	});

	function handleModeChange(newMode: 'predefined' | 'custom') {
		mode = newMode;
	}
</script>

<div class="flex flex-col gap-3">
	<!-- Label and Mode Toggle -->
	<div class="flex items-center justify-between gap-3">
		<label class="text-sm font-medium text-default">
			{m.category()} <span class="text-negative-default">*</span>
		</label>

		<!-- Compact Segmented Control -->
		<div class="inline-flex gap-0 rounded-lg border border-default bg-secondary p-1">
			<button
				type="button"
				class="rounded-md px-3 py-1 text-xs font-medium transition-all {mode === 'predefined'
					? 'bg-primary text-default shadow-sm'
					: 'text-secondary hover:text-default'}"
				onclick={() => handleModeChange('predefined')}
			>
				{m.predefined()}
			</button>
			<button
				type="button"
				class="rounded-md px-3 py-1 text-xs font-medium transition-all {mode === 'custom'
					? 'bg-primary text-default shadow-sm'
					: 'text-secondary hover:text-default'}"
				onclick={() => handleModeChange('custom')}
			>
				{m.custom()}
			</button>
		</div>
	</div>

	<!-- Description -->
	<p class="text-xs text-secondary">
		{m.category_selector_description()}
	</p>

	<!-- Selector or Input based on mode -->
	{#if mode === 'predefined'}
		<div class="flex flex-col gap-2" transition:fade={{ duration: 150 }}>
			<button
				id="category-selector"
				{...$trigger}
				use:trigger
				type="button"
				aria-label={m.select_category()}
				class="flex h-10 items-center justify-between rounded-lg border border-default px-3 hover:bg-hover-default"
			>
				<span class="text-default">
					{predefinedCategories[predefinedValue]?.title || m.select_category()}
				</span>
				<IconChevronDown class="text-dimmer" />
			</button>

			{#if $open}
				<div
					class="z-50 flex max-h-64 flex-col overflow-y-auto rounded-lg border border-default bg-primary shadow-xl"
					{...$menu}
					use:menu
					transition:fade={{ duration: 150 }}
				>
					{#each categoryKeys as categoryKey (categoryKey)}
						<div
							class="flex min-h-10 items-center justify-between border-b border-default px-3 last:border-b-0 hover:cursor-pointer hover:bg-hover-default"
							{...$option({ value: categoryKey })}
							use:option
						>
							<div class="flex flex-col gap-0.5">
								<span class="text-sm text-default">
									{predefinedCategories[categoryKey].title}
								</span>
								<span class="text-xs text-dimmer">
									{predefinedCategories[categoryKey].description}
								</span>
							</div>
							<div class="check {$isSelected(categoryKey) ? 'block' : 'hidden'}">
								<IconCheck class="text-positive-default" />
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{:else}
		<div class="flex flex-col gap-2" transition:fade={{ duration: 150 }}>
			<Input.Text
				bind:value={customValue}
				placeholder={m.category_name_placeholder()}
				required
			/>
			<p class="text-xs text-dimmer">
				{m.custom_category_help()}
			</p>
		</div>
	{/if}
</div>

<style lang="postcss">
	@reference '@intric/ui/styles';

	div[data-highlighted] {
		@apply bg-hover-dimmer;
	}

	div[data-disabled] {
		@apply opacity-30 hover:bg-transparent;
	}
</style>
