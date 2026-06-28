export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();
  const selectedCollectionId = event.params.collectionId;
  event.depends("blobs:list");

  const [group, blobs] = await Promise.all([
    eneo.groups.get({ id: selectedCollectionId }),
    eneo.groups.listInfoBlobs({ id: selectedCollectionId })
  ]);

  const isNotSpaceOwner = group.space_id !== currentSpace.id;

  return {
    collection: group,
    blobs,
    selectedCollectionId,
    readonly: isNotSpaceOwner
  };
};
