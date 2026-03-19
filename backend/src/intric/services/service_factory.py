from uuid import UUID

from fastapi import Depends, Path

from intric.groups_legacy.api.group_models import Group
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.services.output_parsing.output_parser_factory import OutputParserFactory
from intric.services.service import Service


async def get_runner_from_service(
    id: UUID = Path(), container: Container = Depends(get_container(with_user=True))
):
    service, _ = await container.service_service().get_service(id)

    return get_service_runner(container=container, service=service)


def get_service_runner(
    container: Container,
    service: Service,
    with_groups: list[Group] = None,
):
    if with_groups is not None:
        service.groups = with_groups  # type: ignore[assignment]

    output_parser = OutputParserFactory.create(service)
    prompt = f"{service.prompt}\n{output_parser.get_format_instructions()}"

    return container.service_runner(
        service=service, output_parser=output_parser, prompt=prompt
    )
