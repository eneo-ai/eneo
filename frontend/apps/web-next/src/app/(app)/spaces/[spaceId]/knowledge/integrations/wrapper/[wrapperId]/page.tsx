import { WrapperDetail } from "./wrapper-detail.client";

export default async function WrapperPage({
  params
}: {
  params: Promise<{ spaceId: string; wrapperId: string }>;
}) {
  const { wrapperId } = await params;
  return <WrapperDetail wrapperId={wrapperId} />;
}
