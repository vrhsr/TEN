"""
OCRService — downloads a document from S3, runs Tesseract, and returns
structured text suitable for the LLM extraction step.

Supported modes:
  insurance_card  — two-sided card, extracts front/back pages
  facesheet       — single-page hospital face sheet
  generic         — no page assumptions

Dependencies: pytesseract, Pillow, pdf2image (poppler-utils must be installed)
"""
from __future__ import annotations

import io
import os
import tempfile
from typing import Any

try:
    import pytesseract
    from PIL import Image
    from pdf2image import convert_from_bytes
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

from shared.config import get_settings
from shared.logging import get_logger
from .s3_service import S3Service

log = get_logger(__name__)


class OCRService:
    def __init__(self) -> None:
        settings = get_settings()
        if _OCR_AVAILABLE:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
            os.environ.setdefault("TESSDATA_PREFIX", settings.tessdata_prefix)
        self.s3 = S3Service()

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_from_s3(
        self,
        bucket: str,
        key: str,
        mode: str = "insurance_card",
        document_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Download a document from S3 and run OCR.
        Returns a dict with ocr_text (full concatenated), pages (list of page dicts),
        page_count, and mode.
        """
        log.info("ocr.extract_from_s3.start", bucket=bucket, key=key, mode=mode)

        if not _OCR_AVAILABLE:
            log.warning("ocr.tesseract_not_installed")
            return self._stub_result(document_id, mode)

        raw = self.s3.get_bytes(bucket, key)
        mime = self._guess_mime(key)

        if mime == "application/pdf":
            pages = self._extract_pdf(raw)
        else:
            pages = self._extract_image(raw)

        full_text = "\n\n".join(p["text"] for p in pages)
        log.info(
            "ocr.extract_from_s3.done",
            document_id=document_id,
            page_count=len(pages),
            char_count=len(full_text),
        )
        return {
            "document_id": document_id,
            "mode": mode,
            "ocr_text": full_text,
            "page_count": len(pages),
            "pages": pages,
        }

    def extract_from_bytes(
        self,
        data: bytes,
        filename: str = "document.pdf",
        mode: str = "insurance_card",
        document_id: int | None = None,
    ) -> dict[str, Any]:
        if not _OCR_AVAILABLE:
            return self._stub_result(document_id, mode)

        mime = self._guess_mime(filename)
        pages = self._extract_pdf(data) if mime == "application/pdf" else self._extract_image(data)
        full_text = "\n\n".join(p["text"] for p in pages)
        return {
            "document_id": document_id,
            "mode": mode,
            "ocr_text": full_text,
            "page_count": len(pages),
            "pages": pages,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _extract_pdf(self, pdf_bytes: bytes) -> list[dict]:
        """Convert PDF pages to images then run Tesseract on each."""
        images = convert_from_bytes(pdf_bytes, dpi=300)
        return [
            {
                "page": idx + 1,
                "text": pytesseract.image_to_string(img, lang="eng").strip(),
                "confidence": self._mean_confidence(img),
            }
            for idx, img in enumerate(images)
        ]

    def _extract_image(self, img_bytes: bytes) -> list[dict]:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        text = pytesseract.image_to_string(img, lang="eng").strip()
        return [{"page": 1, "text": text, "confidence": self._mean_confidence(img)}]

    @staticmethod
    def _mean_confidence(img) -> float:
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            confs = [c for c in data["conf"] if c != -1]
            return round(sum(confs) / len(confs) / 100, 4) if confs else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _guess_mime(key: str) -> str:
        lower = key.lower()
        if lower.endswith(".pdf"):
            return "application/pdf"
        if lower.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".tiff") or lower.endswith(".tif"):
            return "image/tiff"
        return "application/octet-stream"

    @staticmethod
    def _stub_result(document_id: int | None, mode: str) -> dict:
        return {
            "document_id": document_id,
            "mode": mode,
            "ocr_text": "",
            "page_count": 0,
            "pages": [],
            "_stub": True,
        }
