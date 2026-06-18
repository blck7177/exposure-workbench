"""JSON serialization helpers."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


class ExposureJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def dumps(obj: Any, **kwargs: Any) -> str:
    return json.dumps(obj, cls=ExposureJSONEncoder, **kwargs)


def loads(s: str) -> Any:
    return json.loads(s)
