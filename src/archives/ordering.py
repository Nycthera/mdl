"""Natural ordering for chapter and page names."""

import re
from decimal import Decimal


def _natural_key(value: str):
    return [
        Decimal(part) if index % 2 else part.casefold()
        for index, part in enumerate(re.split(r"(\d+(?:\.\d+)?)", value))
    ]
