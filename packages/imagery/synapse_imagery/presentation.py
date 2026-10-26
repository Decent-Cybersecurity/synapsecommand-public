"""The user-visible imagery detail: one record per product that a consumer's interface renders.

No product interface exists in this repository; this module fixes what one would show and the
exact words it uses. The record names the source product, the actual wire signature, the file
date, each image's capture date or `unknown`, the image count, dimensions, band count and bit
depth, whether a preview is available to the viewer, the pixel capability, the geometry basis,
the content that is retained but not interpreted, and the security display the viewer is
authorised to see. A footprint is labelled "imagery footprint"; missing pixels and missing
coordinates have one fixed sentence each; an image without a usable footprint is never shown
as a map, so an empty map is never presented as a successful geolocation; and every derivative
states that it is segment-only, because no graphic overlay is ever composed.

The record is built from the worker's inventory and the policy's decisions only. Label values
appear only when the caller passes them as authorised; titles, comments, identifiers and corner
text are never in the inventory, so they cannot reach the record.
"""

from __future__ import annotations

FOOTPRINT_LABEL = "imagery footprint"
PIXELS_UNAVAILABLE = "Image data preserved; this encoding is not supported by this deployment."
NO_FOOTPRINT = "No usable geographic footprint."
UNKNOWN = "unknown"
SCHEMA = "sc-imagery-presentation/1"


def _date_text(date: dict) -> str:
    return date["utc"] if date["status"] == "valid" else UNKNOWN


def _geometry_basis(image: dict, diagnostics: list[dict]) -> str | None:
    """IGEOLO when ICORDS is G or D. The inventory carries the status, not ICORDS: blank ICORDS is
    the `absent` status, and a coordinate system other than G and D is the one finding reported
    at the ICORDS field (GEOMETRY_UNSUPPORTED); every other status comes from G or D corners."""
    if image["geometry_status"] == "absent":
        return None
    other = f"/segments/image[{image['index']}]/ICORDS"
    if any(
        entry["code"] == "GEOMETRY_UNSUPPORTED" and entry["path"] == other for entry in diagnostics
    ):
        return None
    return "IGEOLO"


def unsupported_content(inventory: dict) -> list[str]:
    """What the container holds that nothing here interprets, in a fixed order: unrecognised
    extensions, graphics (retained, never rendered), each image's pixels and footprint when they
    are not usable, and a display composition that could not be resolved."""
    tokens = []
    counts = inventory["extension_counts"]
    for kind in ("tre", "des", "res"):
        if counts[kind]:
            tokens.append(f"{kind}:{counts[kind]}:not_interpreted")
    graphics = sum(1 for segment in inventory["segments"] if segment["kind"] == "graphic")
    if graphics:
        tokens.append(f"graphic:{graphics}:not_rendered")
    for image in inventory["images"]:
        index = image["index"]
        if image["pixel_status"] != "native_supported":
            tokens.append(f"image[{index}]:pixels:{image['pixel_reason']}")
        if image["geometry_status"] in ("unsupported", "invalid"):
            tokens.append(f"image[{index}]:geometry:{image['geometry_status']}")
    if inventory["composition_status"] == "unavailable":
        tokens.append("composition:unavailable")
    return tokens


def build(
    inventory: dict,
    *,
    product_entity_id: str | None,
    preview_allowed: bool,
    labels_authorised: bool,
    labels: list | None,
    derivatives: list[dict],
) -> dict:
    """The presentation record of one inventoried container."""
    from synapse_imagery.policy import SecurityDescriptor

    if type(preview_allowed) is not bool or type(labels_authorised) is not bool:
        raise TypeError("the viewer's decisions are bools")
    if labels is not None and not labels_authorised:
        raise ValueError("labels are shown only when the viewer is authorised to see them")
    descriptor = SecurityDescriptor.from_json(inventory["descriptor"])
    diagnostics = inventory["diagnostics"]
    images = []
    for image in inventory["images"]:
        native = image["pixel_status"] == "native_supported"
        located = image["geometry_status"] == "available"
        images.append(
            {
                "index": image["index"],
                "capture_date": _date_text(image["capture_date"]),
                "rows": image["nrows"],
                "columns": image["ncols"],
                "bands": image["bands"],
                "bits_per_sample": image["nbpp"],
                "significant_bits": image["abpp"],
                "preview": "available" if native and preview_allowed else "not_available",
                "pixel_capability": image["pixel_status"],
                "pixel_message": None if native else PIXELS_UNAVAILABLE,
                "geometry_basis": _geometry_basis(image, diagnostics),
                "geometry_status": image["geometry_status"],
                "footprint_label": FOOTPRINT_LABEL if located else None,
                "geometry_message": None if located else NO_FOOTPRINT,
                "map": "footprint" if located else "none",
            }
        )
    return {
        "schema": SCHEMA,
        "source_product_id": product_entity_id,
        "wire_signature": inventory["signature"],
        "file_date": _date_text(inventory["file_date"]),
        "image_count": len(images),
        "images": images,
        "unsupported_content": unsupported_content(inventory),
        "security_display": {
            "authorised": labels_authorised,
            "status": descriptor.assessment["status"],
            "labels": labels if labels_authorised else None,
        },
        "derivatives": [
            {
                "derivative_id": entry["derivative_id"],
                "image_index": entry["image_index"],
                "composition": "segment_only",
            }
            for entry in derivatives
        ],
    }
