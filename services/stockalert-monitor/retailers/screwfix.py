from .base import BaseRetailer, register


@register("screwfix")
class ScrewfixRetailer(BaseRetailer):
    display_name = "Screwfix"
    domains = ["screwfix.com"]
    use_playwright = False
    positive_indicators = BaseRetailer.positive_indicators + ["add to basket"]
    negative_indicators = BaseRetailer.negative_indicators + ["out of stock"]
