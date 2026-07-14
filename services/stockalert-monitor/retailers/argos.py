from .base import BaseRetailer, register


@register("argos")
class ArgosRetailer(BaseRetailer):
    display_name = "Argos"
    domains = ["argos.co.uk"]
    # Argos blocks automated requests (403); fetch via FlareSolverr.
    use_flaresolverr = True
    # Argos embeds JSON-LD availability (handled by the base parser).
    negative_indicators = BaseRetailer.negative_indicators + [
        "check stock",
        "not available for home delivery",
    ]
