"use client";

import { useScrollableArea } from "@astryxdesign/core/hooks";
import { useTranslator } from "@astryxdesign/core/i18n";
import * as React from "react";

import { cn } from "@/lib/utils";

// No `ref`: the scrollable-area hook owns the <table>'s ref to measure it.
function Table({ className, ...props }: Omit<React.ComponentProps<"table">, "ref">) {
  const t = useTranslator();
  // A table wider than its container scrolls sideways, and the keyboard must
  // reach that scroll too (2.1.1): Tab goes to the first link or button in
  // the table, or else the container is a named stop while it overflows.
  // Astryx's own Table does the same with this hook (a group, not a landmark,
  // and the same label); the hook also owns the container's overflow.
  const { getViewportProps, getContentProps } = useScrollableArea({
    axis: "inline",
    keyboardAccess: {
      owner: "contentOrViewport",
      label: props["aria-label"] ?? t("@astryx.table.label"),
      role: "group"
    },
    overscroll: "contain"
  });
  return (
    <div
      {...getViewportProps<HTMLDivElement>({
        "data-slot": "table-container",
        className: "relative w-full"
      })}
      // A table named by a heading names its scroll region the same way.
      aria-labelledby={props["aria-labelledby"]}
    >
      <table
        {...props}
        {...getContentProps<HTMLTableElement>({
          "data-slot": "table",
          className: cn("w-full caption-bottom text-sm", className)
        })}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead data-slot="table-header" className={cn("[&_tr]:border-b", className)} {...props} />;
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn("bg-muted/50 border-t font-medium [&>tr]:last:border-b-0", className)}
      {...props}
    />
  );
}

type TableRowProps = React.ComponentProps<"tr"> & {
  onRowAction?: () => void;
};

function TableRow({
  className,
  onClick,
  onKeyDown,
  onRowAction,
  tabIndex,
  ...props
}: TableRowProps) {
  const actionable = Boolean(onRowAction);

  const handleClick: React.MouseEventHandler<HTMLTableRowElement> = (event) => {
    onClick?.(event);
    if (!event.defaultPrevented) onRowAction?.();
  };

  const handleKeyDown: React.KeyboardEventHandler<HTMLTableRowElement> = (event) => {
    onKeyDown?.(event);
    if (event.defaultPrevented || !onRowAction) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onRowAction();
  };

  return (
    <tr
      data-slot="table-row"
      onClick={onClick || onRowAction ? handleClick : undefined}
      onKeyDown={onKeyDown || onRowAction ? handleKeyDown : undefined}
      tabIndex={tabIndex ?? (actionable ? 0 : undefined)}
      className={cn(
        "hover:bg-muted/50 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted border-b transition-colors",
        className
      )}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "p-2 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className
      )}
      {...props}
    />
  );
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("text-muted-foreground mt-4 text-sm", className)}
      {...props}
    />
  );
}

export { Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption };
