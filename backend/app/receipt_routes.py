"""Receipt scanning, synchronous processing, and background job routes."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from .auth import get_current_household_id
from .database import SessionLocal, get_db
from .models import ReceiptJob
from .receipt_pantry_service import (
    DuplicateReceiptError,
    calculate_receipt_hash,
    find_processed_receipt,
    process_receipt_into_pantry,
)
from .receipt_service import (
    BlankReceiptImageError,
    InvalidReceiptContentError,
    InvalidReceiptFileError,
    ReceiptExtractionError,
    ReceiptServiceUnavailableError,
    UnreadableReceiptError,
    extract_receipt_data_from_bytes,
    validate_receipt_financials,
)
from .schemas import (
    ReceiptJobCreatedResponse,
    ReceiptJobStatusResponse,
    ReceiptProcessResponse,
    ReceiptScanResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/receipts",
    tags=["Receipt scanning"],
)

RECEIPT_EXTRACTION_TIMEOUT_SECONDS = 120
BACKGROUND_EXTRACTION_TIMEOUT_SECONDS = int(
    os.getenv("RECEIPT_BACKGROUND_TIMEOUT_SECONDS", "600")
)
BACKGROUND_EXPECTED_EXTRACTION_SECONDS = max(
    20,
    int(os.getenv("RECEIPT_EXPECTED_EXTRACTION_SECONDS", "75")),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _read_receipt_upload(
    file: UploadFile,
) -> tuple[bytes, str, str | None]:
    """Read the uploaded receipt and close the uploaded file."""

    filename = file.filename or "receipt.jpg"
    content_type = file.content_type

    try:
        file_bytes = await file.read()
    finally:
        await file.close()

    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded receipt file is empty.",
        )

    return file_bytes, filename, content_type


async def _extract_receipt(
    file_bytes: bytes,
    filename: str,
    content_type: str | None,
):
    """Extract receipt data with controlled timeout and error handling."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                extract_receipt_data_from_bytes,
                file_bytes,
                filename,
                content_type,
            ),
            timeout=RECEIPT_EXTRACTION_TIMEOUT_SECONDS,
        )

    except asyncio.TimeoutError as exc:
        logger.warning(
            "Receipt extraction exceeded the %s-second timeout.",
            RECEIPT_EXTRACTION_TIMEOUT_SECONDS,
        )

        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "Receipt processing took too long. "
                "Please use background processing for long receipts."
            ),
        ) from exc

    except BlankReceiptImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except UnreadableReceiptError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except InvalidReceiptContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except InvalidReceiptFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    except ReceiptServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except ReceiptExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


def _set_job_progress(
    db: Session,
    job: ReceiptJob,
    *,
    progress: int,
    stage: str,
    estimated_seconds_remaining: int | None,
) -> None:
    """Persist progress so polling works across page refreshes."""

    job.progress = max(0, min(int(progress), 100))
    job.stage = stage
    job.estimated_seconds_remaining = (
        max(0, int(estimated_seconds_remaining))
        if estimated_seconds_remaining is not None
        else None
    )
    db.commit()


def _safe_job_error(exc: Exception) -> str:
    """Return a user-safe message while keeping detailed logs server-side."""

    if isinstance(
        exc,
        (
            BlankReceiptImageError,
            UnreadableReceiptError,
            InvalidReceiptContentError,
            InvalidReceiptFileError,
            ReceiptServiceUnavailableError,
            ReceiptExtractionError,
            DuplicateReceiptError,
        ),
    ):
        return str(exc)

    if isinstance(exc, asyncio.TimeoutError):
        return (
            "Receipt processing exceeded the background time limit. "
            "Please try again shortly."
        )

    return (
        "The receipt could not be processed safely. "
        "No partial pantry changes were saved."
    )


async def _extract_for_background_job(
    db: Session,
    job: ReceiptJob,
    file_bytes: bytes,
    filename: str,
    content_type: str | None,
):
    """Run Gemini extraction while publishing approximate progress and ETA."""

    extraction_task = asyncio.create_task(
        asyncio.to_thread(
            extract_receipt_data_from_bytes,
            file_bytes,
            filename,
            content_type,
        )
    )

    started = time.perf_counter()

    while not extraction_task.done():
        elapsed = time.perf_counter() - started
        expected = BACKGROUND_EXPECTED_EXTRACTION_SECONDS

        # Extraction occupies 20%-72% of the job. The percentage is an
        # estimate because Gemini does not stream token-level progress.
        progress = 20 + min(50, int((elapsed / expected) * 50))
        remaining = max(5, int(expected - elapsed)) + 15

        _set_job_progress(
            db,
            job,
            progress=progress,
            stage="Reading and extracting receipt items",
            estimated_seconds_remaining=remaining,
        )

        try:
            await asyncio.wait_for(
                asyncio.shield(extraction_task),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            if elapsed >= BACKGROUND_EXTRACTION_TIMEOUT_SECONDS:
                extraction_task.cancel()
                raise asyncio.TimeoutError

    return await extraction_task


async def _process_receipt_job(
    job_id: str,
    file_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> None:
    """Execute a receipt job after the upload request has already returned."""

    db = SessionLocal()

    try:
        job = db.get(ReceiptJob, job_id)
        if job is None:
            logger.error("Receipt job %s disappeared before processing.", job_id)
            return

        job.status = "processing"
        job.started_at = _utc_now()
        job.error_message = None
        _set_job_progress(
            db,
            job,
            progress=5,
            stage="Validating receipt upload",
            estimated_seconds_remaining=(
                BACKGROUND_EXPECTED_EXTRACTION_SECONDS + 20
            ),
        )

        # The existing receipt service performs file, blank-image, and blur
        # validation before sending anything to Gemini.
        _set_job_progress(
            db,
            job,
            progress=15,
            stage="Preparing receipt image",
            estimated_seconds_remaining=(
                BACKGROUND_EXPECTED_EXTRACTION_SECONDS + 15
            ),
        )

        receipt_data = await _extract_for_background_job(
            db,
            job,
            file_bytes,
            filename,
            content_type,
        )

        _set_job_progress(
            db,
            job,
            progress=76,
            stage="Validating extracted receipt totals",
            estimated_seconds_remaining=12,
        )

        # This call preserves the existing all-or-nothing pantry transaction,
        # duplicate protection, ML sample creation, and grocery reconciliation.
        _set_job_progress(
            db,
            job,
            progress=84,
            stage="Creating pantry batches",
            estimated_seconds_remaining=8,
        )

        result = process_receipt_into_pantry(
            db=db,
            household_id=job.household_id,
            receipt=receipt_data,
            file_hash=job.file_hash,
            original_filename=filename,
            content_type=content_type,
        )

        _set_job_progress(
            db,
            job,
            progress=95,
            stage="Finalizing pantry sync",
            estimated_seconds_remaining=2,
        )

        job.status = "completed"
        job.progress = 100
        job.stage = "Receipt processed successfully"
        job.estimated_seconds_remaining = 0
        job.result_data = result.model_dump(mode="json")
        job.completed_at = _utc_now()
        db.commit()

    except Exception as exc:
        db.rollback()
        logger.exception("Background receipt job %s failed.", job_id)

        job = db.get(ReceiptJob, job_id)
        if job is not None:
            job.status = "failed"
            job.stage = "Receipt processing failed"
            job.estimated_seconds_remaining = 0
            job.error_message = _safe_job_error(exc)
            job.completed_at = _utc_now()
            db.commit()

    finally:
        db.close()


@router.post(
    "/scan",
    response_model=ReceiptScanResponse,
    status_code=status.HTTP_200_OK,
)
async def scan_receipt(
    file: Annotated[
        UploadFile,
        File(description="Receipt image to scan without updating Smart Pantry"),
    ],
) -> ReceiptScanResponse:
    """Scan a receipt without updating the pantry."""

    started = time.perf_counter()
    file_bytes, filename, content_type = await _read_receipt_upload(file)
    receipt_data = await _extract_receipt(file_bytes, filename, content_type)
    financial_validation = validate_receipt_financials(receipt_data)

    logger.info(
        "Receipt scan endpoint completed in %.2f seconds",
        time.perf_counter() - started,
    )

    return ReceiptScanResponse(
        success=True,
        receipt=receipt_data,
        financial_validation=financial_validation,
    )


@router.post(
    "/process",
    response_model=ReceiptProcessResponse,
    status_code=status.HTTP_200_OK,
)
async def process_receipt(
    file: Annotated[
        UploadFile,
        File(description="Receipt image to scan and add to Smart Pantry"),
    ],
    household_id: str = Depends(get_current_household_id),
    db: Session = Depends(get_db),
) -> ReceiptProcessResponse:
    """Preserve the existing synchronous receipt-processing endpoint."""

    total_started = time.perf_counter()
    file_bytes, filename, content_type = await _read_receipt_upload(file)
    file_hash = calculate_receipt_hash(file_bytes)

    existing_receipt = find_processed_receipt(
        db=db,
        household_id=household_id,
        file_hash=file_hash,
    )

    if existing_receipt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This receipt has already been processed.",
        )

    receipt_data = await _extract_receipt(file_bytes, filename, content_type)

    try:
        result = process_receipt_into_pantry(
            db=db,
            household_id=household_id,
            receipt=receipt_data,
            file_hash=file_hash,
            original_filename=filename,
            content_type=content_type,
        )
    except DuplicateReceiptError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Receipt was scanned but pantry update failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Receipt was scanned, but the pantry could not be updated. "
                "No pantry changes were saved."
            ),
        ) from exc

    logger.info(
        "Receipt process endpoint completed in %.2f seconds",
        time.perf_counter() - total_started,
    )
    return result


@router.post(
    "/jobs",
    response_model=ReceiptJobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_receipt_job(
    background_tasks: BackgroundTasks,
    file: Annotated[
        UploadFile,
        File(description="Receipt image to process in the background"),
    ],
    household_id: str = Depends(get_current_household_id),
    db: Session = Depends(get_db),
) -> ReceiptJobCreatedResponse:
    """Accept a receipt immediately and process it after returning a job ID."""

    file_bytes, filename, content_type = await _read_receipt_upload(file)
    file_hash = calculate_receipt_hash(file_bytes)

    if find_processed_receipt(db, household_id, file_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This receipt has already been processed.",
        )

    active_job = (
        db.query(ReceiptJob)
        .filter(
            ReceiptJob.household_id == household_id,
            ReceiptJob.file_hash == file_hash,
            ReceiptJob.status.in_(["queued", "processing"]),
        )
        .order_by(ReceiptJob.created_at.desc())
        .first()
    )

    if active_job is not None:
        return ReceiptJobCreatedResponse(
            job_id=active_job.id,
            status=active_job.status,
            progress=active_job.progress,
            stage=active_job.stage,
            estimated_seconds_remaining=(
                active_job.estimated_seconds_remaining
            ),
        )

    job = ReceiptJob(
        household_id=household_id,
        file_hash=file_hash,
        original_filename=filename,
        content_type=content_type,
        status="queued",
        progress=0,
        stage="Receipt queued",
        estimated_seconds_remaining=(
            BACKGROUND_EXPECTED_EXTRACTION_SECONDS + 20
        ),
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(
        _process_receipt_job,
        job.id,
        file_bytes,
        filename,
        content_type,
    )

    return ReceiptJobCreatedResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        estimated_seconds_remaining=job.estimated_seconds_remaining,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ReceiptJobStatusResponse,
)
def get_receipt_job(
    job_id: str,
    household_id: str = Depends(get_current_household_id),
    db: Session = Depends(get_db),
) -> ReceiptJobStatusResponse:
    """Return progress, ETA, final result, or a safe failure message."""

    job = (
        db.query(ReceiptJob)
        .filter(
            ReceiptJob.id == job_id,
            ReceiptJob.household_id == household_id,
        )
        .first()
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt processing job not found.",
        )

    result = None
    if job.result_data is not None:
        result = ReceiptProcessResponse.model_validate(job.result_data)

    return ReceiptJobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        estimated_seconds_remaining=job.estimated_seconds_remaining,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=result,
        error=job.error_message,
    )