from .base import BaseRetailer, register


@register("ao")
class AORetailer(BaseRetailer):
    display_name = "AO"
    domains = ["ao.com"]
    # AO fronts product pages with a bot wall; fetch via FlareSolverr.
    use_flaresolverr = True
    positive_indicators = BaseRetailer.positive_indicators + ["add to basket"]
