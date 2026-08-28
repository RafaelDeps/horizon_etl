import math
import os
from typing import Any, List

from loguru import logger
from pydantic import BaseModel

from src.core.logic.atomic_io import atomic_write_json
from src.core.ports.export_sink import IExportSink


class JsonSink(IExportSink):
    def export(self, data: List[Any], path: str) -> None:
        """
        Exports data to a JSON file.

        Args:
            data: List of Pydantic models or SQLAlchemy objects.
            path: Destination file path.
        """
        try:
            # Ensure directory exists
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

            # Internal serializer helper
            def serialize(obj):
                import enum
                from datetime import date, datetime

                if isinstance(obj, enum.Enum):
                    return obj.value

                if isinstance(obj, (date, datetime)):
                    return obj.isoformat()

                # NaN/Infinity are not strict JSON; emit null instead so every
                # canonical export stays parseable by strict consumers.
                if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                    return None

                if obj is None or isinstance(obj, (bool, int, float, str)):
                    return obj

                if isinstance(obj, dict):
                    return {k: serialize(v) for k, v in obj.items()}

                if isinstance(obj, list):
                    return [serialize(i) for i in obj]

                if isinstance(obj, BaseModel):
                    return obj.model_dump(mode="json")

                # Check for SQLAlchemy model (has __table__)
                if hasattr(obj, "__table__"):
                    return {
                        c.name: serialize(getattr(obj, c.name))
                        for c in obj.__table__.columns
                    }

                if hasattr(obj, "__dict__"):
                    return serialize(obj.__dict__)

                return str(obj)

            json_data = [serialize(item) for item in data]

            atomic_write_json(path, json_data, indent=4, ensure_ascii=False)

            logger.info(f"Successfully exported {len(data)} items to {path}")

        except Exception as e:
            logger.error(f"Failed to export data to {path}: {e}")
            raise e
