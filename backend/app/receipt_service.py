"""Gemini-based receipt extraction and validation service.

The original uploaded image bytes are never modified. WasteWise creates an
in-memory optimized copy only for the Gemini request, while the frontend keeps
showing the exact original file selected by the user.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import time
from datetime import date
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import (
    Image,
    ImageFilter,
    ImageOps,
    ImageStat,
    UnidentifiedImageError,
)
from pydantic import ValidationError

from .schemas import (
    ReceiptData,
    ReceiptFinancialValidation,
)


load_dotenv()

logger = logging.getLogger(__name__)


MAX_RECEIPT_SIZE_BYTES = 10 * 1024 * 1024

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

EXTENSION_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


RECEIPT_EXTRACTION_PROMPT = """
Extract this retail receipt into the supplied JSON schema.

GENERAL RULES
- Extract only purchased product lines.
- Never treat merchant details, dates, headings, subtotal, tax, total, payment,
  change, service charges, delivery charges, discounts, or terms as products.
- Do not invent unreadable values. Use null when a value cannot be read.
- Keep raw_name close to the printed text.
- product_name should be clean and human-readable.
- pantry_name should be a short generic household name with brands, package
  sizes, counts, weights, marketing words, and store-brand names removed.
- Mark household, cleaning, hygiene, stationery, cosmetic, and other non-food
  products with is_food_item=false.
- Add uncertain values to uncertain_fields.

QUANTITY AND PACKAGE RULES
- Keep purchased_quantity separate from package_size.
- "Milk 1L, Qty 2" means purchased_quantity=2, package_size=1, package_unit="l".
- Loose weighted produce uses the measured weight as purchased_quantity and
  package_size=null.
- Countable packs such as 12 eggs use package_size=12 and package_unit="piece".
- If no quantity is printed, use purchased_quantity=null.
- Allowed package_unit values:
  g, kg, ml, l, oz, fl_oz, lb, gal, pint, quart, piece, pack, unknown.

PANTRY NORMALIZATION EXAMPLES
- Great Value Large Eggs 12 count -> pantry_name="Eggs"
- 365 Organic Milk 2% 1/2 gal -> pantry_name="Milk"
- Chobani Greek Yogurt Plain 5.3 oz -> pantry_name="Greek Yogurt"
- Tyson Chicken Breast 2.5 lb -> pantry_name="Chicken Breast"
- Mission Flour Tortillas 10 count -> pantry_name="Tortillas"
- Driscoll's Strawberries 1 lb -> pantry_name="Strawberries"
- Annie's Mac & Cheese Shells 6 oz -> pantry_name="Macaroni & Cheese"
- Coca-Cola 12 oz 18 Pack -> pantry_name="Soft Drink"
- Gatorade Arctic Blitz 20 oz -> pantry_name="Sports Drink"
- Nutella -> pantry_name="Hazelnut Spread"
- Biskrem Duo -> pantry_name="Cookies"

CLASSIFICATION
- Allowed categories:
  beverage, dairy, fruit, grain, meat, snack, vegetable, other.
- Allowed storage locations:
  fridge, freezer, pantry, unknown.
- Infer category and storage conservatively.

DATE AND CURRENCY
- Extract purchase_date only when visible and reliable; format YYYY-MM-DD.
- Otherwise return purchase_date=null.
- Always return purchase_date_source=null; the backend fills it later.
- Use PKR, USD, GBP, or EUR as appropriate.

SHELF LIFE
- For each food item, estimate a conservative typical shelf life in days from
  purchase, based on pantry_name, whether it is fresh/frozen/dried/canned or
  shelf-stable, and its storage location.
- This is an estimate, not a manufacturer expiry date.
- expiry_confidence must be between 0 and 1.
- expiry_reason should briefly explain the estimate.
- Do not claim to have searched the web.

FINANCIALS
- Extract items_subtotal, tax_amount, tax_rate, service_charge,
  delivery_charge, other_charges, discount_amount, total_amount,
  payment_amount, and change_amount when printed.
- Financial equation:
  items_subtotal + tax_amount + service_charge + delivery_charge
  + other_charges - discount_amount = total_amount.
- Do not include financial rows as products.

Return only valid structured data matching the supplied schema.
"""


class InvalidReceiptFileError(ValueError):
    """Raised when the uploaded file itself is invalid."""


class BlankReceiptImageError(ValueError):
    """Raised when the uploaded image is blank or nearly uniform."""


class UnreadableReceiptError(ValueError):
    """Raised when no useful receipt content can be extracted."""


class InvalidReceiptContentError(ValueError):
    """Raised when the image contains no purchased product lines."""


class ReceiptExtractionError(RuntimeError):
    """Raised when Gemini returns unusable receipt data."""


class ReceiptServiceUnavailableError(RuntimeError):
    """Raised when Gemini is unavailable or unreachable."""


def _resolve_mime_type(
    filename: str,
    declared_content_type: str | None,
) -> str:
    """Determine the uploaded receipt image MIME type."""

    normalized_content_type = (
        declared_content_type.lower().strip()
        if declared_content_type
        else None
    )

    if normalized_content_type in ALLOWED_MIME_TYPES:
        return normalized_content_type

    suffix = Path(filename).suffix.lower()

    extension_mime_type = (
        EXTENSION_MIME_TYPES.get(suffix)
    )

    if extension_mime_type:
        return extension_mime_type

    guessed_mime_type, _ = mimetypes.guess_type(
        filename
    )

    if guessed_mime_type in ALLOWED_MIME_TYPES:
        return guessed_mime_type

    raise InvalidReceiptFileError(
        "Unsupported receipt format. Upload a JPG, JPEG, "
        "JFIF, PNG, or WEBP image."
    )


def _validate_image(
    file_bytes: bytes,
) -> None:
    """
    Confirm that the uploaded bytes contain a valid, non-blank,
    sufficiently clear receipt image.

    Validation happens before Gemini is called.
    """

    if not file_bytes:
        raise InvalidReceiptFileError(
            "The uploaded receipt file is empty."
        )

    if len(file_bytes) > MAX_RECEIPT_SIZE_BYTES:
        raise InvalidReceiptFileError(
            "Receipt image must be 10 MB or smaller."
        )

    try:
        # First verify that the bytes represent a real image.
        with Image.open(
            BytesIO(file_bytes)
        ) as image:
            image.verify()

        # Reopen because verify() closes the internal image parser.
        with Image.open(
            BytesIO(file_bytes)
        ) as image:
            image = ImageOps.exif_transpose(
                image
            )
            image.load()

            width, height = image.size

            if width < 100 or height < 100:
                raise InvalidReceiptFileError(
                    "The receipt image is too small. "
                    "Please upload a larger, clearer image."
                )

            grayscale = image.convert("L")

            # Analyze a copy so the original upload remains untouched.
            analysis_image = grayscale.copy()
            analysis_image.thumbnail(
                (700, 700)
            )

            statistics = ImageStat.Stat(
                analysis_image
            )

            average_brightness = (
                statistics.mean[0]
            )

            brightness_variation = (
                statistics.stddev[0]
            )

            (
                minimum_brightness,
                maximum_brightness,
            ) = analysis_image.getextrema()

            # ---------------- Blank-image detection ----------------

            nearly_uniform = (
                brightness_variation < 2.5
                or (
                    maximum_brightness
                    - minimum_brightness
                ) < 8
            )

            nearly_white = (
                average_brightness > 248
                and brightness_variation < 6
            )

            nearly_black = (
                average_brightness < 7
                and brightness_variation < 6
            )

            if (
                nearly_uniform
                or nearly_white
                or nearly_black
            ):
                raise BlankReceiptImageError(
                    "The uploaded image appears to be blank. "
                    "Please upload a clear photo of a receipt."
                )

            # ---------------- Blur detection ----------------
            #
            # FIND_EDGES highlights sharp text and receipt boundaries.
            # A heavily blurred receipt produces weak edge variation.

            edge_image = analysis_image.filter(
                ImageFilter.FIND_EDGES
            )

            edge_width, edge_height = (
                edge_image.size
            )

            # Remove artificial outer edges introduced by FIND_EDGES.
            crop_margin_x = max(
                1,
                int(edge_width * 0.05),
            )

            crop_margin_y = max(
                1,
                int(edge_height * 0.05),
            )

            if (
                edge_width > crop_margin_x * 2
                and edge_height > crop_margin_y * 2
            ):
                edge_image = edge_image.crop(
                    (
                        crop_margin_x,
                        crop_margin_y,
                        edge_width
                        - crop_margin_x,
                        edge_height
                        - crop_margin_y,
                    )
                )

            edge_statistics = ImageStat.Stat(
                edge_image
            )

            edge_strength = (
                edge_statistics.mean[0]
            )

            edge_variation = (
                edge_statistics.stddev[0]
            )

            blur_edge_threshold = float(
                os.getenv(
                    "RECEIPT_BLUR_EDGE_THRESHOLD",
                    "8.0",
                )
            )

            blur_variation_threshold = float(
                os.getenv(
                    "RECEIPT_BLUR_VARIATION_THRESHOLD",
                    "18.0",
                )
            )

            appears_blurry = (
                edge_variation
                < blur_edge_threshold
                and brightness_variation
                < blur_variation_threshold
            )

            severely_blurry = (
                edge_strength < 3.0
                and edge_variation < 10.0
            )

            logger.info(
                (
                    "Receipt quality check: size=%sx%s, "
                    "brightness=%.2f, contrast=%.2f, "
                    "edge_strength=%.2f, edge_variation=%.2f"
                ),
                width,
                height,
                average_brightness,
                brightness_variation,
                edge_strength,
                edge_variation,
            )

            if (
                appears_blurry
                or severely_blurry
            ):
                raise UnreadableReceiptError(
                    "The receipt image is too blurry to read reliably. "
                    "Please upload a sharper, well-lit photo."
                )

    except (
        BlankReceiptImageError,
        UnreadableReceiptError,
        InvalidReceiptFileError,
    ):
        raise

    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise InvalidReceiptFileError(
            "The uploaded file is not a valid image."
        ) from exc


def _prepare_image_for_gemini(
    file_bytes: bytes,
    mime_type: str,
) -> tuple[bytes, str]:
    """Create an optimized in-memory copy for Gemini."""

    max_dimension = int(
        os.getenv(
            "RECEIPT_IMAGE_MAX_DIMENSION",
            "2000",
        )
    )

    jpeg_quality = int(
        os.getenv(
            "RECEIPT_IMAGE_JPEG_QUALITY",
            "88",
        )
    )

    max_dimension = max(
        1200,
        min(max_dimension, 3000),
    )

    jpeg_quality = max(
        75,
        min(jpeg_quality, 95),
    )

    try:
        with Image.open(
            BytesIO(file_bytes)
        ) as image:
            image = ImageOps.exif_transpose(
                image
            )
            image.load()

            width, height = image.size
            largest_dimension = max(
                width,
                height,
            )

            if largest_dimension > max_dimension:
                scale = (
                    max_dimension
                    / largest_dimension
                )

                image = image.resize(
                    (
                        max(
                            1,
                            round(width * scale),
                        ),
                        max(
                            1,
                            round(height * scale),
                        ),
                    ),
                    Image.Resampling.LANCZOS,
                )

            # Keep small transparent PNGs as PNG.
            if (
                mime_type == "image/png"
                and len(file_bytes) <= 1_500_000
                and image.mode in {"RGBA", "LA"}
            ):
                output = BytesIO()

                image.save(
                    output,
                    format="PNG",
                    optimize=True,
                )

                return (
                    output.getvalue(),
                    "image/png",
                )

            if image.mode not in {"RGB", "L"}:
                background = Image.new(
                    "RGB",
                    image.size,
                    "white",
                )

                if "A" in image.getbands():
                    background.paste(
                        image,
                        mask=image.getchannel("A"),
                    )
                else:
                    background.paste(image)

                image = background

            elif image.mode == "L":
                image = image.convert("RGB")

            output = BytesIO()

            image.save(
                output,
                format="JPEG",
                quality=jpeg_quality,
                optimize=True,
                progressive=True,
            )

            return (
                output.getvalue(),
                "image/jpeg",
            )

    except Exception as exc:
        logger.warning(
            "Receipt image optimization failed; "
            "using original image: %s",
            exc,
        )

        return file_bytes, mime_type


def _set_purchase_date_source(
    receipt_data: ReceiptData,
) -> None:
    """Validate purchase date or use the upload date."""

    if receipt_data.purchase_date:
        try:
            date.fromisoformat(
                receipt_data.purchase_date
            )

        except ValueError:
            receipt_data.purchase_date = (
                date.today().isoformat()
            )

            receipt_data.purchase_date_source = (
                "upload_date"
            )

        else:
            receipt_data.purchase_date_source = (
                "receipt"
            )

        return

    receipt_data.purchase_date = (
        date.today().isoformat()
    )

    receipt_data.purchase_date_source = (
        "upload_date"
    )


def _validate_extracted_receipt(
    receipt_data: ReceiptData,
) -> None:
    """Confirm that Gemini extracted meaningful receipt content."""

    items = receipt_data.items or []

    meaningful_items = [
        item
        for item in items
        if (
            (
                getattr(
                    item,
                    "raw_name",
                    None,
                )
                and item.raw_name.strip()
            )
            or (
                getattr(
                    item,
                    "product_name",
                    None,
                )
                and item.product_name.strip()
            )
        )
    ]

    merchant_name = (
        receipt_data.merchant_name.strip()
        if receipt_data.merchant_name
        else ""
    )

    has_financial_information = any(
        value is not None
        for value in (
            receipt_data.items_subtotal,
            receipt_data.tax_amount,
            receipt_data.total_amount,
            receipt_data.payment_amount,
        )
    )

    if not meaningful_items:
        if (
            not merchant_name
            and not has_financial_information
        ):
            raise UnreadableReceiptError(
                "No readable receipt content was found. "
                "Please upload a sharper, well-lit receipt image."
            )

        raise InvalidReceiptContentError(
            "The image was read, but no purchased products "
            "were found. Please upload a complete shopping receipt."
        )


def validate_receipt_financials(
    receipt: ReceiptData,
) -> ReceiptFinancialValidation:
    """Validate receipt subtotal, tax, charges, and total."""

    known_line_totals = [
        float(item.line_total)
        for item in receipt.items
        if item.line_total is not None
    ]

    missing_line_totals = sum(
        1
        for item in receipt.items
        if item.line_total is None
    )

    line_items_total = round(
        sum(known_line_totals),
        2,
    )

    printed_subtotal = (
        float(receipt.items_subtotal)
        if receipt.items_subtotal
        is not None
        else None
    )

    receipt_total = (
        float(receipt.total_amount)
        if receipt.total_amount
        is not None
        else None
    )

    currency = (
        receipt.currency
        or "PKR"
    ).strip().upper()

    base_tolerance = (
        1.0
        if currency
        in {
            "PKR",
            "JPY",
            "KRW",
        }
        else 0.02
    )

    reference_amount = max(
        abs(receipt_total or 0),
        abs(printed_subtotal or 0),
        abs(line_items_total),
    )

    tolerance = max(
        base_tolerance,
        round(
            reference_amount * 0.001,
            2,
        ),
    )

    notes: list[str] = []

    if missing_line_totals:
        notes.append(
            f"{missing_line_totals} item(s) did not have "
            "a readable line total."
        )

    if (
        printed_subtotal is not None
        and known_line_totals
    ):
        subtotal_difference = round(
            abs(
                printed_subtotal
                - line_items_total
            ),
            2,
        )

        if subtotal_difference > 0:
            if subtotal_difference <= tolerance:
                notes.append(
                    "The sum of extracted product lines "
                    f"differs from the printed subtotal by "
                    f"{subtotal_difference:.2f}, which is "
                    "within the allowed rounding tolerance."
                )

            else:
                notes.append(
                    "The sum of extracted product lines "
                    f"differs from the printed subtotal by "
                    f"{subtotal_difference:.2f}, which "
                    "exceeds the allowed tolerance."
                )

    if printed_subtotal is not None:
        effective_subtotal = (
            printed_subtotal
        )

    elif known_line_totals:
        effective_subtotal = (
            line_items_total
        )

        notes.append(
            "A printed subtotal was unavailable, so the "
            "sum of extracted product lines was used."
        )

    else:
        effective_subtotal = None

    if (
        effective_subtotal is None
        or receipt_total is None
    ):
        return ReceiptFinancialValidation(
            status="unavailable",
            line_items_total=line_items_total,
            items_subtotal=effective_subtotal,
            calculated_total=None,
            receipt_total=receipt_total,
            difference=None,
            tolerance=tolerance,
            missing_line_totals=missing_line_totals,
            notes=notes
            + [
                "There was not enough financial information "
                "to reconcile the receipt."
            ],
        )

    if receipt.tax_amount is not None:
        tax_amount = float(
            receipt.tax_amount
        )

    elif receipt.tax_rate is not None:
        tax_amount = round(
            effective_subtotal
            * float(receipt.tax_rate)
            / 100,
            2,
        )

        notes.append(
            "Tax amount was calculated from the extracted "
            "tax rate because a separate tax amount was "
            "not available."
        )

    else:
        tax_amount = 0.0

    service_charge = float(
        receipt.service_charge or 0
    )

    delivery_charge = float(
        receipt.delivery_charge or 0
    )

    other_charges = float(
        receipt.other_charges or 0
    )

    discount_amount = float(
        receipt.discount_amount or 0
    )

    calculated_total = round(
        effective_subtotal
        + tax_amount
        + service_charge
        + delivery_charge
        + other_charges
        - discount_amount,
        2,
    )

    difference = round(
        abs(
            calculated_total
            - receipt_total
        ),
        2,
    )

    reconciled = (
        difference <= tolerance
    )

    if reconciled:
        if printed_subtotal is not None:
            notes.append(
                "The printed subtotal, tax, charges, "
                "discounts, and final receipt total "
                "reconcile."
            )

        else:
            notes.append(
                "The product-line total, tax, charges, "
                "discounts, and final receipt total "
                "reconcile."
            )

    else:
        notes.append(
            "The calculated receipt total does not match "
            "the printed receipt total."
        )

    return ReceiptFinancialValidation(
        status=(
            "reconciled"
            if reconciled
            else "mismatch"
        ),
        line_items_total=line_items_total,
        items_subtotal=round(
            effective_subtotal,
            2,
        ),
        calculated_total=calculated_total,
        receipt_total=round(
            receipt_total,
            2,
        ),
        difference=difference,
        tolerance=tolerance,
        missing_line_totals=missing_line_totals,
        notes=notes,
    )


def _classify_gemini_failure(
    exc: Exception,
) -> ReceiptExtractionError:
    """Convert Gemini errors into safe user-facing errors."""

    message = str(exc).lower()

    timeout_markers = (
        "timeout",
        "timed out",
        "deadline exceeded",
    )

    unavailable_markers = (
        "service unavailable",
        "temporarily unavailable",
        "connection",
        "network",
        "503",
        "429",
        "resource exhausted",
        "rate limit",
    )

    if any(
        marker in message
        for marker in timeout_markers
    ):
        return ReceiptServiceUnavailableError(
            "The receipt AI service took too long to respond. "
            "Please try again shortly."
        )

    if any(
        marker in message
        for marker in unavailable_markers
    ):
        return ReceiptServiceUnavailableError(
            "The receipt AI service is temporarily unavailable. "
            "Please try again shortly."
        )

    return ReceiptExtractionError(
        "The receipt could not be analysed. "
        "Please try again with a clearer image."
    )


def extract_receipt_data_from_bytes(
    file_bytes: bytes,
    filename: str,
    declared_content_type: str | None = None,
) -> ReceiptData:
    """Send receipt bytes to Gemini and validate the result."""

    _validate_image(
        file_bytes
    )

    mime_type = _resolve_mime_type(
        filename=filename,
        declared_content_type=(
            declared_content_type
        ),
    )

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:
        logger.error(
            "GEMINI_API_KEY is missing."
        )

        raise ReceiptServiceUnavailableError(
            "Receipt scanning is temporarily unavailable. "
            "Please contact support if the problem continues."
        )

    model_name = os.getenv(
        "GEMINI_MODEL"
    )

    if not model_name:
        logger.error(
            "GEMINI_MODEL is missing."
        )

        raise ReceiptServiceUnavailableError(
            "Receipt scanning is temporarily unavailable. "
            "Please contact support if the problem continues."
        )

    (
        processing_bytes,
        processing_mime_type,
    ) = _prepare_image_for_gemini(
        file_bytes,
        mime_type,
    )

    logger.info(
        "Receipt image prepared for Gemini: "
        "original=%d bytes, optimized=%d bytes, mime=%s",
        len(file_bytes),
        len(processing_bytes),
        processing_mime_type,
    )

    client = genai.Client(
        api_key=api_key
    )

    request_started = (
        time.perf_counter()
    )

    try:
        response = (
            client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(
                        data=processing_bytes,
                        mime_type=(
                            processing_mime_type
                        ),
                    ),
                    RECEIPT_EXTRACTION_PROMPT,
                ],
                config=(
                    types.GenerateContentConfig(
                        response_mime_type=(
                            "application/json"
                        ),
                        response_json_schema=(
                            ReceiptData
                            .model_json_schema()
                        ),
                        temperature=0,
                        max_output_tokens=int(
                            os.getenv(
                                "RECEIPT_MAX_OUTPUT_TOKENS",
                                "8192",
                            )
                        ),
                    )
                ),
            )
        )

    except Exception as exc:
        logger.exception(
            "Gemini receipt extraction failed "
            "after %.2f seconds",
            (
                time.perf_counter()
                - request_started
            ),
        )

        raise _classify_gemini_failure(
            exc
        ) from exc

    finally:
        client.close()

    logger.info(
        "Gemini receipt extraction completed "
        "in %.2f seconds",
        (
            time.perf_counter()
            - request_started
        ),
    )

    if not response.text:
        raise UnreadableReceiptError(
            "No readable receipt content was found. "
            "Please upload a sharper, well-lit receipt image."
        )

    try:
        receipt_data = (
            ReceiptData.model_validate_json(
                response.text
            )
        )

    except ValidationError as exc:
        logger.warning(
            "Gemini returned invalid structured "
            "receipt data: %s",
            exc,
        )

        raise ReceiptExtractionError(
            "The receipt was detected, but its information "
            "could not be processed safely. Please try again."
        ) from exc

    _validate_extracted_receipt(
        receipt_data
    )

    _set_purchase_date_source(
        receipt_data
    )

    return receipt_data