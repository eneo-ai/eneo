import asyncio
from enum import Enum
from typing import TYPE_CHECKING

from intric.libs.clients import AsyncClient
from intric.main.config import get_settings

if TYPE_CHECKING:
    pass


class FluxModel(str, Enum):
    FLUX_1_DEV = "flux-dev"
    FLUX_1_PRO = "flux-pro"
    FLUX_1_1_PRO = "flux-pro-1.1"
    FLUX_1_1_PRO_ULTRA = "flux-pro-1.1-ultra"


class FluxAdapter:
    BASE_URL = "https://api.us1.bfl.ai/v1"

    def __init__(self):
        self.client = AsyncClient(base_url=self.BASE_URL)
        self.headers = {
            "x-key": get_settings().flux_api_key,
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        model: FluxModel = FluxModel.FLUX_1_DEV,
        width: int = 800,
        height: int = 608,
    ):
        async with self.client as client:
            data = {"prompt": prompt, "width": width, "height": height}

            res = await client.post(
                endpoint=model.value, data=data, headers=self.headers
            )

            request_id = res["id"]

            data = {}

            while True:
                await asyncio.sleep(0.5)

                result = await client.get(
                    endpoint="get_result",
                    params={"id": request_id},
                    headers=self.headers,
                )

                if result["status"] == "Ready":
                    image_url = result["result"]["sample"]

                    return await client.download(url=image_url)
