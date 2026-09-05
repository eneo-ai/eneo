<script lang="ts">
  import type { Action } from "svelte/action";
  import { cva } from "class-variance-authority";

  export let label: string | undefined = undefined;
  export let href: string | undefined = undefined;
  export let type: HTMLButtonElement["type"] | undefined = undefined;
  export let unstyled = false;

  /**
   * Pass melt-ui builders into the `is` property to apply them to this button
   * Typically you would do this when you have a trigger as fragment, so the child
   * actually does the triggering.
   */
  export let is: {
    [x: PropertyKey]: unknown;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    action: Action<HTMLElement, any, Record<string, unknown>>;
  }[] = [];

  let cls = "";
  export { cls as class };

  export let variant:
    | "simple"
    | "outlined"
    | "primary"
    | "primary-outlined"
    | "destructive"
    | "warning-outlined"
    | "positive"
    | "positive-outlined"
    | "on-fill" = "simple";
  export let padding: "icon" | "text" | "icon-leading" = "text";
  // export let size: "base" = "base";
  export let disabled: boolean | undefined = undefined;
  export let displayActiveState: boolean = false;

  const button = cva(
    [
      "group",
      "flex",
      "items-center",
      "justify-center",
      "gap-3",
      "rounded-md",
      "border",
      "text-left",
      "mix-blend-normal",
      "outline-offset-4",
      "data-[melt-dropdown-menu-item]:justify-start"
    ],
    {
      variants: {
        intent: {
          simple: ["border-transparent", "hover:border-dimmer", "hover:bg-hover-default"],
          outlined: ["border-default", "hover:bg-hover-default"],
          primary: [
            "border-accent-default",
            "bg-accent-default",
            "text-on-fill",
            "hover:border-accent-stronger",
            "hover:bg-accent-stronger"
          ],
          "primary-outlined": [
            "border-accent-default",
            "bg-transparent",
            "text-accent-default",
            "hover:border-accent-stronger",
            "hover:bg-accent-stronger",
            "hover:text-on-fill"
          ],
          "warning-outlined": [
            "border-warning-default",
            "text-warning-stronger",
            "hover:border-warning-stronger",
            "hover:bg-warning-dimmer"
          ],
          destructive: [
            "border-negative-default",
            "text-negative-default",
            "hover:border-negative-default",
            "hover:bg-negative-default",
            "hover:text-on-fill"
          ],
          positive: [
            "border-positive-stronger",
            "bg-positive-default",
            "text-on-fill",
            "hover:border-positive-default",
            "hover:bg-positive-stronger"
          ],
          "positive-outlined": [
            "border-positive-stronger",
            "text-positive-stronger",
            "hover:border-positive-default",
            "hover:bg-positive-stronger",
            "hover:text-on-fill"
          ],
          "on-fill": [
            "border-transparent",
            "hover:border-dimmer",
            "hover:bg-hover-on-fill",
            "hover:text-primary"
          ]
        },
        padding: { icon: ["p-1"], text: ["py-1", "px-2"], "icon-leading": ["p-1", "pr-2"] },
        disabled: {
          false: null,
          true: ["pointer-events-none", "cursor-not-allowed", "opacity-50"]
        },
        displayActiveState: {
          false: null,
          true: [
            "tracking-[0.01rem]",
            'data-[state="active"]:bg-accent-dimmer',
            'data-[state="active"]:font-[500]',
            'data-[state="active"]:tracking-normal',
            'data-[state="active"]:text-accent-stronger'
          ]
        }
      }
    }
  );

  export let actions: Action[] = [() => {}];

  const combinedActions = (node: HTMLElement) => {
    const destructors = actions.map((action) => action(node));
    const meltDestructurs = is.map((builder) => builder.action(node));

    return {
      destroy() {
        destructors.forEach((destructor) => {
          if (typeof destructor?.destroy == "function") destructor.destroy();
        });
        meltDestructurs.forEach((destructor) => {
          if (typeof destructor?.destroy == "function") destructor.destroy();
        });
      }
    };
  };

  $: meltAttributes = is.reduce(
    (attrs, melt) => {
      Object.keys(melt).forEach((key) => {
        if (key !== "action") {
          attrs[key] = melt[key];
        }
      });
      return attrs;
    },
    {} as { [x: PropertyKey]: unknown }
  );
</script>

<svelte:element
  this={href ? "a" : "button"}
  type={href ? undefined : type}
  {href}
  aria-label={label}
  aria-disabled={disabled}
  disabled={disabled ? true : undefined}
  on:click
  on:change
  on:keydown
  on:keyup
  on:mouseenter
  on:mouseleave
  tabindex="0"
  use:combinedActions
  {...meltAttributes}
  {...$$restProps}
  class={[
    unstyled ? cls : button({ intent: variant, padding, disabled, displayActiveState, class: cls }),
    "cursor-pointer"
  ]}
>
  <slot />
</svelte:element>
