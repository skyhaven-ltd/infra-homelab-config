from .base import BaseRetailer, register


@register("generic")
class GenericRetailer(BaseRetailer):
    """Fallback for any product URL whose domain has no dedicated plugin.

    Relies entirely on the base detector: escalating fetch (static ->
    FlareSolverr -> Playwright) and JSON-LD/indicator-phrase stock parsing.
    The notification shows the site's hostname as the retailer name.
    """

    display_name = "Web shop"
    domains: list[str] = []
