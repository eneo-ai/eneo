export const load = async (event) => {
  const { eneo } = await event.parent();
  const selectedServiceId = event.params.serviceId;

  event.depends("service:get");

  const service = await eneo.services.get({ id: selectedServiceId });

  return { service, selectedServiceId };
};
