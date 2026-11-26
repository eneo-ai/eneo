export const load = async (event) => {
  const { eneo } = await event.parent();
  const groupChat = await eneo.groupChats.get({ id: event.params.groupChatId });
  return { groupChat };
};
