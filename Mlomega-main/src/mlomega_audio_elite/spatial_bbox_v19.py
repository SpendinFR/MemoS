from __future__ import annotations

"""Validated detector-pixel bounding boxes shared by VisionRT and WorldBrain.

The detector frame is the only authoritative coordinate space.  Materialised
keyframes/previews may have another size and must never be used to reinterpret a
tracker box.
"""

from dataclasses import dataclass
import math
from typing import Any, Sequence


@dataclass(frozen=True)
class BBoxValidation:
    bbox: tuple[float, float, float, float] | None
    raw: tuple[float, float, float, float] | None
    status: str
    reasons: tuple[str, ...]
    frame_width: int | None
    frame_height: int | None
    coordinate_space: str = "detector_pixels"

    @property
    def usable(self) -> bool:
        return self.bbox is not None

    def audit_dict(self) -> dict[str, Any]:
        return {
            "bbox_raw": list(self.raw) if self.raw is not None else None,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "bbox_status": self.status,
            "bbox_reasons": list(self.reasons),
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "coordinate_space": self.coordinate_space,
        }


def sanitize_detector_bbox(
    raw: Any,
    *,
    frame_width: int | float | None,
    frame_height: int | float | None,
    require_dimensions: bool = True,
    min_area_px: float = 1.0,
) -> BBoxValidation:
    """Return a finite, ordered and in-frame detector-pixel bbox or reject it."""

    reasons: list[str] = []
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        return BBoxValidation(
            None, None, "rejected", ("not_four_numbers",), None, None
        )
    if len(values) != 4:
        return BBoxValidation(
            None, None, "rejected", ("not_four_numbers",), None, None
        )
    if not all(math.isfinite(value) for value in values):
        return BBoxValidation(
            None, values, "rejected", ("non_finite",), None, None
        )

    try:
        width = int(frame_width) if frame_width is not None else None
        height = int(frame_height) if frame_height is not None else None
    except (TypeError, ValueError, OverflowError):
        width = height = None
    dimensions_valid = bool(width and width > 0 and height and height > 0)
    if require_dimensions and not dimensions_valid:
        return BBoxValidation(
            None, values, "rejected", ("missing_frame_dimensions",), width, height
        )

    x1_raw, y1_raw, x2_raw, y2_raw = values
    x1, x2 = sorted((x1_raw, x2_raw))
    y1, y2 = sorted((y1_raw, y2_raw))
    if (x1, y1, x2, y2) != values:
        reasons.append("reordered")

    if dimensions_valid:
        assert width is not None and height is not None
        clamped = (
            min(max(x1, 0.0), float(width)),
            min(max(y1, 0.0), float(height)),
            min(max(x2, 0.0), float(width)),
            min(max(y2, 0.0), float(height)),
        )
        if clamped != (x1, y1, x2, y2):
            reasons.append("clamped_to_detector_frame")
        x1, y1, x2, y2 = clamped
    elif min(x1, y1, x2, y2) < 0:
        return BBoxValidation(
            None, values, "rejected", ("negative_without_dimensions",), width, height
        )

    area = (x2 - x1) * (y2 - y1)
    if x2 <= x1 or y2 <= y1 or area < float(min_area_px):
        return BBoxValidation(
            None,
            values,
            "rejected",
            tuple([*reasons, "degenerate_area"]),
            width,
            height,
        )
    status = "normalized" if reasons else ("valid" if dimensions_valid else "legacy_valid")
    return BBoxValidation(
        (x1, y1, x2, y2), values, status, tuple(reasons), width, height
    )
