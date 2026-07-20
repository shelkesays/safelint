"""FastAPI + Pydantic input schema - ``extra = "allow"`` is the SAFE906 trigger.

Only fires when ``pydantic = true`` composes on top of the FastAPI framework
preset (the FastAPI preset alone does not enable mass_assignment).
"""

from pydantic import BaseModel


class ItemIn(BaseModel):
    name: str

    class Config:
        extra = "allow"
