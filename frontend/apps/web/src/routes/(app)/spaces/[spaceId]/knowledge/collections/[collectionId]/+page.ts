export const load = async (event) => {
  const { intric, currentSpace } = await event.parent();
  const selectedCollectionId = event.params.collectionId;
  event.depends("blobs:list");

  const [group, blobs] = await Promise.all([
    intric.groups.get({ id: selectedCollectionId }),
    intric.groups.listInfoBlobs({ id: selectedCollectionId })
  ]);

   const isNotSpaceOwner = group.space_id !== currentSpace.id;

  return { 
    collection: group, 
    blobs, 
    selectedCollectionId,
    readonly: isNotSpaceOwner
  };
};