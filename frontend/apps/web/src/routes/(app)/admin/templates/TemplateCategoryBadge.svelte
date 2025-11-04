<script lang="ts">
	import {
		assistantTemplateCategories,
		appTemplateCategories,
		getCategoryInfo
	} from '$lib/features/templates/TemplateCategories';

	interface Props {
		category: string;
		type?: 'assistant' | 'app';
	}

	let { category, type = 'assistant' }: Props = $props();

	const predefinedCategories =
		type === 'assistant' ? assistantTemplateCategories : appTemplateCategories;
	const categoryInfo = getCategoryInfo(category, predefinedCategories);
</script>

<span
	class="inline-flex items-center rounded-md bg-accent-dimmer px-2 py-1 text-xs font-medium text-accent-stronger"
	title={categoryInfo.description}
>
	{categoryInfo.title}
</span>
