from typing import Literal

from loyalty_service.promotions.schemas import StrictModel


class ResolveInput(StrictModel):
    outcome: Literal['succeeded', 'failed']
