<script lang="ts">
	import { untrack } from 'svelte';
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

	interface Props {
		value?: string;
		type: 'assistant' | 'app';
	}

	let { value = $bindable(''), type }: Props = $props();

	const predefinedCategories =
		type === 'assistant' ? assistantTemplateCategories : appTemplateCategories;
	const categoryKeys = Object.keys(predefinedCategories);

	// Mode: true = predefined, false = custom
	let isPredefined = $state(true);
	let customValue = $state('');
	let predefinedValue = $state(categoryKeys[0] || '');

	// Ensure initial value is set for predefined mode
	$effect(() => {
		if (isPredefined && !value && predefinedValue) {
			value = predefinedValue;
		}
	});

	// Initialize mode and values based on incoming value
	$effect(() => {
		if (value) {
			if (categoryKeys.includes(value)) {
				isPredefined = true;
				predefinedValue = value;
			} else {
				isPredefined = false;
				customValue = value;
			}
		}
	});

	// Update external value when mode or internal values change
	$effect(() => {
		if (isPredefined) {
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
		defaultSelected: { value: untrack(() => predefinedValue) },
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

</script>

<div class="flex flex-col gap-4">
	<!-- Mode Toggle using RadioSwitch for consistency -->
	<!-- Note: Label and description come from Settings.Row parent -->
	<Input.RadioSwitch
		bind:value={isPredefined}
		labelTrue={m.predefined()}
		labelFalse={m.custom()}
	/>

	<!-- Selector or Input based on mode -->
	<div class="flex flex-col gap-2">
		{#if isPredefined}
				<button
					{...$trigger}
					use:trigger
					type="button"
					aria-label={m.select_category()}
					class="flex h-11 items-center justify-between rounded-lg border border-default px-4 py-2.5 hover:bg-hover-default"
				>
					<span class="text-sm font-medium text-default">
						{predefinedCategories[predefinedValue]?.title || m.select_category()}
					</span>
					<IconChevronDown class="text-dimmer" />
				</button>

				{#if $open}
					<div
						class="z-50 flex max-h-64 flex-col overflow-y-auto rounded-lg border border-default bg-primary shadow-xl"
						{...$menu}
						use:menu
					>
						{#each categoryKeys as categoryKey (categoryKey)}
							<div
								class="flex min-h-12 items-center justify-between border-b border-default px-4 py-3 last:border-b-0 hover:cursor-pointer hover:bg-hover-default"
								{...$option({ value: categoryKey })}
								use:option
							>
								<div class="flex flex-col gap-1">
									<span class="text-sm font-medium text-default">
										{predefinedCategories[categoryKey].title}
									</span>
									<span class="text-sm text-secondary">
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
		{:else}
			<Input.Text
				bind:value={customValue}
				placeholder={m.category_name_placeholder()}
				required
				hiddenLabel={true}
			/>
			<p class="text-sm text-secondary">
				{m.custom_category_help()}
			</p>
		{/if}
	</div>
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
