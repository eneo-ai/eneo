import { Separator } from "@/components/ui/separator";

/** Section of related settings rows with a group heading. */
export function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      <Separator />
      <div className="flex flex-col gap-8">{children}</div>
    </section>
  );
}

/** Label + description on the left, control on the right (stacks on small screens). */
export function SettingsRow({
  title,
  description,
  children
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <div className="flex flex-col gap-1">
        <h3 className="font-medium">{title}</h3>
        {description ? <p className="text-muted-foreground text-sm">{description}</p> : null}
      </div>
      <div className="flex min-w-0 flex-col gap-2">{children}</div>
    </div>
  );
}
