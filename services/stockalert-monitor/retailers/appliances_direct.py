from .base import BaseRetailer, register


@register("appliances_direct")
class AppliancesDirectRetailer(BaseRetailer):
    display_name = "Appliances Direct"
    domains = ["appliancesdirect.co.uk"]
    use_playwright = False
    positive_indicators = BaseRetailer.positive_indicators + ["in stock", "add to basket"]
