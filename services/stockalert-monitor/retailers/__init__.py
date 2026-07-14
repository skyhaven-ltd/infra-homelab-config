"""Retailer plugins.

Importing this package registers every retailer class in the shared registry.
To add a retailer: create ``retailers/<name>.py`` with a ``@register("<name>")``
class declaring its ``domains``, then import it below. URLs on unknown domains
fall back to the generic detector automatically.
"""

from .base import (
    BaseRetailer,
    StockResult,
    get_retailer,
    register,
    registered_keys,
    resolve_retailer,
)

# Import each module for its @register side effect.
from . import (  # noqa: F401  (imported for registration)
    amazon,
    ao,
    appliances_direct,
    argos,
    bq,
    currys,
    generic,
    screwfix,
    toolstation,
    very,
)

__all__ = [
    "BaseRetailer",
    "StockResult",
    "get_retailer",
    "register",
    "registered_keys",
    "resolve_retailer",
]
