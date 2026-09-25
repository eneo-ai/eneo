export function PageHeader({
  title,
  tour,
  children
}: {
  title: string;
  tour?: string;
  children?: React.ReactNode;
}) {
  return (
    <div data-tour={tour} className="flex min-h-9 items-center justify-between gap-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {children ? <div className="flex items-center gap-2">{children}</div> : null}
    </div>
  );
}
