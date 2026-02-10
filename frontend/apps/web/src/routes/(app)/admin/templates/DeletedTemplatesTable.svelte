<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { m } from "$lib/paraglide/messages";
  import TemplateDeletedActions from "./TemplateDeletedActions.svelte";
  import TemplateNameCell from "./TemplateNameCell.svelte";
  import TemplateCategoryBadge from "./TemplateCategoryBadge.svelte";
  import dayjs from "dayjs";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let { templates }: { templates: Template[] } = $props();

  const table = Table.createWithResource(templates);

  function isAppTemplate(template: Template): template is AppTemplate {
    return "input_type" in template;
  }

  const viewModel = table.createViewModel([
    table.column({
      accessor: "name",
      header: m.template_name(),
      cell: (item) => {
        return createRender(TemplateNameCell, {
          name: item.value,
          description: item.row.original.description,
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
      accessor: (template) => (isAppTemplate(template) ? "App" : "Assistant"),
      header: m.type(),
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
        const type = isAppTemplate(item.row.original) ? "app" : "assistant";
        return createRender(TemplateCategoryBadge, {
          category: item.value,
          type: type
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
      accessor: "deleted_at",
      header: m.deleted_date(),
      cell: (item) => {
        if (!item.value) return "-";
        return dayjs(item.value).format("YYYY-MM-DD HH:mm");
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value ? new Date(value).getTime() : 0;
          }
        }
      }
    }),

    table.columnActions({
      cell: (item) => {
        const type = isAppTemplate(item.value) ? "app" : "assistant";
        return createRender(TemplateDeletedActions, { template: item.value, type });
      }
    })
  ]);

  $effect(() => {
    table.update(templates);
  });
</script>

<Table.Root {viewModel} resourceName={m.deleted_templates()} displayAs="list" />
