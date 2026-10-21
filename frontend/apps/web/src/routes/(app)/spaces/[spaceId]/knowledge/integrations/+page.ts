import { redirect } from "@sveltejs/kit";

// The integrations live on a tab of the knowledge page; this address is what
// people type or trim a source URL down to.
export const load = ({ params }: { params: { spaceId: string } }) => {
  throw redirect(307, `/spaces/${params.spaceId}/knowledge?tab=integrations`);
};
