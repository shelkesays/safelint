"""Django request-chain injection - SAFE801 once ``tainted_sink`` is enabled.

Each view flows a request projection (attribute / subscript / method chain on
the tainted ``request`` parameter) into a Django-preset SAFE801 sink
(``RawSQL`` / ``mark_safe``). All three fire only because taint now propagates
through the request projection; ``safe`` routes the same data through a
context-appropriate sanitiser (HTML ``escape`` into the HTML-context
``mark_safe`` sink) and is the negative control. This is the real
request-driven injection detection the framework presets exist to provide.
"""


def by_attribute(request):
    return RawSQL(request.data)


def by_subscript(request):
    return mark_safe(request.GET["q"])


def by_method(request):
    return RawSQL(request.GET.get("q"))


def safe(request):
    # escape() is HTML-escaping, so it is the context-appropriate sanitiser for
    # the HTML-context sink mark_safe (NOT for RawSQL - HTML escaping does not
    # make SQL safe). Sink-specific sanitiser properties are the P3 roadmap item.
    return mark_safe(escape(request.GET.get("q")))
