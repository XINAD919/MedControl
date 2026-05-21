"""
Document upload and listing endpoints.

POST /api/users/{user_id}/documents  — upload prescription image or PDF
GET  /api/users/{user_id}/documents  — list user's uploaded documents
"""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel

from core.db import create_document, get_user_documents, update_document_processing
from deps import CurrentUser, get_current_user
from core.embeddings import generate_and_save_embeddings
from core.ocr import process_prescription
from core.storage import upload_prescription

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}
_MAX_SIZE = 10 * 1024 * 1024  # 10 MB


class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_type: str | None
    document_type: str
    file_size: int | None
    processed: bool
    chunk_count: int
    uploaded_at: str
    processing: bool = False


async def _process_document_background(
    doc_id: str,
    user_id: str,
    file_bytes: bytes,
    mimetype: str,
) -> None:
    """Run OCR + embedding generation after the HTTP response is returned."""
    try:
        ocr_result = await process_prescription(file_bytes, mimetype)

        if not ocr_result.raw_text:
            error_detail = ocr_result.structured.raw_notes or "Claude OCR returned empty text"
            logger.error("OCR produced no text for doc %s: %s", doc_id, error_detail)
            await update_document_processing(doc_id, f"[OCR error: {error_detail}]", 0)
            return

        chunk_count = await generate_and_save_embeddings(
            doc_id, user_id, ocr_result.raw_text
        )
        await update_document_processing(doc_id, ocr_result.raw_text, chunk_count)
        logger.info("Document %s processed: %d chunks", doc_id, chunk_count)
    except Exception as e:
        logger.error("OCR background task failed for doc %s: %s", doc_id, e, exc_info=True)
        try:
            await update_document_processing(doc_id, f"[Processing error: {e}]", 0)
        except Exception:
            pass


@router.post(
    "/users/{user_id}/documents", response_model=DocumentResponse, status_code=201
)
async def upload_document(
    user_id: str,
    background_tasks: BackgroundTasks,
    file: Annotated[
        UploadFile, File(description="Prescription image (JPEG/PNG/WEBP) or PDF")
    ],
    description: Annotated[str | None, Form()] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="No autorizado")

    content_type = file.content_type or "application/octet-stream"

    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{content_type}'. Allowed: JPEG, PNG, WEBP, PDF.",
        )

    file_bytes = await file.read()
    file_size = len(file_bytes)

    if file_size > _MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file_size // 1024} KB). Maximum is 10 MB.",
        )

    filename = file.filename or "prescription.jpg"

    # 1. Upload to Supabase Storage
    try:
        storage_path = await upload_prescription(
            user_id,
            filename,
            file_bytes,
            content_type,
        )
        print(f"storage_path: {storage_path}")
    except Exception as e:
        logger.error("Storage upload failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to upload file to storage.")

    # 2. Create DB record
    doc_id = await create_document(
        user_id=user_id,
        filename=filename,
        file_type=content_type,
        file_path=storage_path,
        file_size=file_size,
        document_type="prescription",
    )

    # 3. Schedule OCR + embedding as a background task
    background_tasks.add_task(
        _process_document_background, doc_id, user_id, file_bytes, content_type
    )

    return DocumentResponse(
        id=doc_id,
        filename=filename,
        file_type=content_type,
        document_type="prescription",
        file_size=file_size,
        processed=False,
        chunk_count=0,
        uploaded_at="",
        processing=True,
    )


@router.get("/users/{user_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="No autorizado")
    rows = await get_user_documents(user_id)
    return [
        DocumentResponse(
            id=str(row["id"]),
            filename=row["filename"],
            file_type=row.get("file_type"),
            document_type=str(row.get("document_type", "prescription")),
            file_size=row.get("file_size"),
            processed=bool(row.get("processed", False)),
            chunk_count=int(row.get("chunk_count", 0)),
            uploaded_at=str(row.get("uploaded_at", "")),
        )
        for row in rows
    ]
