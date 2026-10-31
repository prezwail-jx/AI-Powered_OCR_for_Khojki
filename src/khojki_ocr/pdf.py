"""Full-page RGB rendering and crop-relative PyMuPDF coordinate transforms."""

import hashlib
import math
from pathlib import Path

import numpy as np
import pymupdf


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def matrix_from_pymupdf(matrix) -> np.ndarray:
    a, b, c, d, e, f = matrix
    return np.array([[a, c, e], [b, d, f], [0.0, 0.0, 1.0]], dtype=float)


def transform_points(points, matrix) -> np.ndarray:
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    homogeneous = np.column_stack([points, np.ones(len(points))])
    mapped = homogeneous @ np.asarray(matrix, dtype=float).T
    return mapped[:, :2] / mapped[:, 2:3]


def map_box(box, matrix) -> dict:
    """Map all four corners; an axis-aligned box becomes a polygon after rotation."""
    x0, y0, x1, y1 = box
    polygon = transform_points([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], matrix)
    minimum, maximum = polygon.min(axis=0), polygon.max(axis=0)
    return {"polygon": polygon.tolist(), "bbox": [*minimum.tolist(), *maximum.tolist()]}


def validate_document(document, pages: list[int]) -> None:
    if not document.is_pdf or document.needs_pass or document.page_count == 0:
        raise ValueError("Input must be a readable, nonempty, unencrypted PDF")
    if not pages or min(pages) < 1 or max(pages) > document.page_count:
        raise ValueError(f"Requested page exceeds PDF page count ({document.page_count}) or is not positive")


def render_page(document, page_number: int, dpi: int, max_pixels: int) -> tuple[np.ndarray, dict]:
    validate_document(document, [page_number])
    if not 72 <= dpi <= 600:
        raise ValueError("DPI must be between 72 and 600")
    page = document[page_number - 1]
    scale = dpi / 72
    predicted = math.ceil(page.rect.width * scale) * math.ceil(page.rect.height * scale)
    if predicted > max_pixels:
        raise ValueError(f"Page {page_number} exceeds max_page_pixels ({predicted} > {max_pixels}); explicitly choose a smaller DPI")
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
    if pixmap.width * pixmap.height > max_pixels:
        raise ValueError("Rendered image exceeds max_page_pixels")
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3).copy()
    rotation = matrix_from_pymupdf(page.rotation_matrix)
    pixels = np.array([[scale, 0, -pixmap.x], [0, scale, -pixmap.y], [0, 0, 1]], dtype=float)
    page_to_raw = pixels @ rotation
    metadata = {
        "page_number": page_number, "dpi": dpi, "page_rotation_degrees": page.rotation,
        "page_rect_points": list(page.rect), "cropbox_points": list(page.cropbox),
        "mediabox_points": list(page.mediabox), "raw_size_pixels": [pixmap.width, pixmap.height],
        "pixmap_origin": [pixmap.x, pixmap.y],
        "embedded_images": [{"width": item[2], "height": item[3]} for item in page.get_images()],
        "coordinate_convention": {
            "page": "PyMuPDF unrotated crop-relative top-left points; not raw PDF bottom-left coordinates",
            "image": "top-left pixel coordinates; x right, y down; boxes use exclusive maximum edges",
            "matrix": "3x3 homogeneous column-vector: destination = H @ [x,y,1]",
        },
        "page_to_raw": page_to_raw.tolist(), "raw_to_page": np.linalg.inv(page_to_raw).tolist(),
        "pymupdf_version": pymupdf.VersionBind,
        "resolution_note": "DPI controls raster size, not recovery of missing embedded scan detail",
    }
    return rgb, metadata
