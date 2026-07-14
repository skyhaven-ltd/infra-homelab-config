from .base import BaseRetailer, register


@register("very")
class VeryRetailer(BaseRetailer):
    display_name = "Very"
    domains = ["very.co.uk"]
    # Very sits behind a bot wall; fetch via FlareSolverr.
    use_flaresolverr = True
    negative_indicators = BaseRetailer.negative_indicators + ["out of stock online"]
