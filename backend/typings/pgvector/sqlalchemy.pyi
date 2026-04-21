from sqlalchemy.types import TypeEngine

class Vector(TypeEngine[list[float]]):
    def __init__(self, *args: object, **kwargs: object) -> None: ...
