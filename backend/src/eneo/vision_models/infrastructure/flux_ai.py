import asyncio
from enum import Enum
from typing import Any

from eneo.libs.clients import AsyncClient
from eneo.main.config import get_settings


class FluxModel(str, Enum):
    FLUX_1_DEV = "flux-dev"
    FLUX_1_PRO = "flux-pro"
    FLUX_1_1_PRO = "flux-pro-1.1"
    FLUX_1_1_PRO_ULTRA = "flux-pro-1.1-ultra"


class FluxAdapter:
    BASE_URL = "https://api.us1.bfl.ai/v1"

    def __init__(self):
        super().__init__()
        api_key = get_settings().flux_api_key
        if api_key is None:
            raise ValueError("FLUX_API_KEY is not configured")

        self.client = AsyncClient(base_url=self.BASE_URL)
        self.headers: dict[str, str] = {
            "x-key": api_key,
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        model: FluxModel = FluxModel.FLUX_1_DEV,
        width: int = 800,
        height: int = 608,
    ) -> bytes:
        async with self.client as client:
            data = {"prompt": prompt, "width": width, "height": height}

            res: dict[str, Any] = await client.post(
                endpoint=model.value, data=data, headers=self.headers
            )

            request_id = str(res["id"])

            while True:
                await asyncio.sleep(0.5)

                result: dict[str, Any] = await client.get(
                    endpoint="get_result",
                    params={"id": request_id},
                    headers=self.headers,
                )

                if result["status"] == "Ready":
                    image_url = str(result["result"]["sample"])

                    return await client.download(url=image_url)
