"""FastAPI fixture - ``reload=True`` (SAFE905) + unvalidated body (SAFE907).

``create`` binds the raw request body into the model with no
validation (SAFE907). ``create_validated`` runs it through
``model_validate`` (negative control). ``serve`` enables uvicorn's
auto-reload, the SAFE905 trigger.
"""

import uvicorn


async def create(request):
    payload = await request.json()
    return Item(**payload)


async def create_validated(request):
    payload = await request.json()
    return Item.model_validate(payload)


def serve():
    uvicorn.run("main:app", reload=True)
