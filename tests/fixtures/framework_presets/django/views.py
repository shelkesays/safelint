"""Django views - unvalidated ``request.data`` bind (SAFE907).

``create`` binds the whole request body into the model with no
serializer (SAFE907 fires). ``create_validated`` routes the same data
through a serializer's ``is_valid()`` (negative control). ``one`` does a
single targeted field read (``request.GET['q']``) which is deliberately
NOT flagged.
"""


def create(request):
    return Item(**request.data)


def create_validated(request):
    serializer = ItemSerializer(data=request.data)
    serializer.is_valid()
    return serializer.save()


def one(request):
    return request.GET["q"]
