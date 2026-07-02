from eneo.database.database import sessionmanager
from eneo.main.logging import get_logger
from eneo.modules.module import ModuleBase, Modules
from eneo.modules.module_repo import ModuleRepository

logger = get_logger(__name__)


async def init_modules():
    try:
        modules = [item.value for item in Modules]
        async with sessionmanager.session() as session, session.begin():
            repository = ModuleRepository(session=session)

            existing_modules = await repository.get_all_modules()
            existing_modules_names = {
                module.name: module.id for module in existing_modules
            }

            # create new modules or update existing
            for name in modules:
                module = ModuleBase(name=name)
                if module.name not in existing_modules_names:
                    await repository.add(module)

    except Exception as e:
        logger.exception(f"Creating modules crashed with next error: {str(e)}")
