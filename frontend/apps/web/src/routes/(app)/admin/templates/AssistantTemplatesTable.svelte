<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { m } from "$lib/paraglide/messages";
  import TemplateActions from "./TemplateActions.svelte";
  import TemplateNameCell from "./TemplateNameCell.svelte";
  import TemplateCategoryBadge from "./TemplateCategoryBadge.svelte";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];

  let { templates }: { templates: AssistantTemplate[] } = $props();

  const table = Table.createWithResource(templates);

  const viewModel = table.createViewModel([
    table.column({
      accessor: "name",
      header: m.template_name(),
      cell: (item) => {
        return createRender(TemplateNameCell, {
          name: item.value,
          description: item.row.original.description,
          isDefault: item.row.original.is_default,
          iconName: item.row.original.icon_name
        });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value;
          }
        },
        tableFilter: {
          getFilterValue(value) {
            return value;
          }
        }
      }
    }),

    table.column({
      accessor: "category",
      header: m.category(),
      cell: (item) => {
        return createRender(TemplateCategoryBadge, {
          category: item.value,
          type: "assistant"
        });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value;
          }
        },
        tableFilter: {
          getFilterValue(value) {
            return value;
          }
        }
      }
    }),

    table.column({
      accessor: (row) => row.usage_count,
      id: "usage_count",
      header: m.usage(),
      cell: (item) => {
        const count = item.value || 0;
        return `${count} ${count === 1 ? m.instance() : m.instances()}`;
      },
      plugins: {
        sort: {
          getSortValue: (v) => v || 0
        }
      }
    }),

    table.column({
      accessor: "created_at",
      header: m.created_date(),
      cell: (item) => {
        const date = new Date(item.value);
        return date.toLocaleDateString();
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return new Date(value).getTime();
          }
        }
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(TemplateActions, { template: item.value, type: "assistant" });
      }
    })
  ]);

  $effect(() => {
    table.update(templates);
  });
</script>

<Table.Root {viewModel} resourceName={m.assistant_templates()} displayAs="list" />
