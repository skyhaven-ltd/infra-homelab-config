from .base import BaseRetailer, register


@register("toolstation")
class ToolstationRetailer(BaseRetailer):
    display_name = "Toolstation"
    domains = ["toolstation.com"]
    use_playwright = False
    positive_indicators = BaseRetailer.positive_indicators + ["add to basket"]
