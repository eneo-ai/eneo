class IntegrationPreview:
    def __init__(
        self,
        name: str,
        url: str,
        type: str,
        key: str,
        category: str | None = None,
    ):
        self.name = name
        self.url = url
        self.type = type
        self.key = key
        self.category = category
