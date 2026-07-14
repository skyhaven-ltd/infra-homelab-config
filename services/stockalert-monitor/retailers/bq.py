from .base import BaseRetailer, register


@register("bq")
class BandQRetailer(BaseRetailer):
    display_name = "B&Q"
    domains = ["diy.com"]
    use_playwright = False
    negative_indicators = BaseRetailer.negative_indicators + ["out of stock for delivery"]
