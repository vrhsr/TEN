"""
LLMService — uses OpenAI to normalize raw OCR text into structured insurance fields.
Uses JSON-mode / function calling so output is always parseable.
"""
from __future__ import annotations

import json
from typing import Any

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)

try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


# ── JSON Schema for structured insurance extraction ───────────────────────────

INSURANCE_CARD_SCHEMA = {
    "name": "insurance_card_extraction",
    "description": "Extract structured fields from raw OCR text of an insurance card or facesheet.",
    "parameters": {
        "type": "object",
        "properties": {
            "member_id": {"type": "string", "description": "Member/subscriber ID (policy number)"},
            "group_number": {"type": "string", "description": "Group number"},
            "payer_name": {"type": "string", "description": "Insurance company name as printed"},
            "plan_name": {"type": "string", "description": "Plan or product name"},
            "subscriber_first_name": {"type": "string"},
            "subscriber_last_name": {"type": "string"},
            "subscriber_dob": {"type": "string", "description": "YYYY-MM-DD if found"},
            "copay_primary": {"type": "string", "description": "Primary care copay amount"},
            "copay_specialist": {"type": "string", "description": "Specialist copay amount"},
            "deductible": {"type": "string", "description": "Deductible amount"},
            "out_of_pocket_max": {"type": "string"},
            "rx_bin": {"type": "string", "description": "Pharmacy BIN number"},
            "rx_pcn": {"type": "string"},
            "rx_group": {"type": "string"},
            "effective_date": {"type": "string", "description": "YYYY-MM-DD"},
            "termination_date": {"type": "string", "description": "YYYY-MM-DD if shown"},
            "plan_type": {
                "type": "string",
                "enum": ["HMO", "PPO", "EPO", "HDHP", "POS", "MEDICARE", "MEDICAID", "UNKNOWN"],
            },
            "confidence_notes": {
                "type": "string",
                "description": "Brief note on extraction quality or ambiguous fields",
            },
        },
        "required": ["member_id", "payer_name"],
        "additionalProperties": False,
    },
}

FACESHEET_SCHEMA = {
    "name": "facesheet_extraction",
    "description": "Extract patient demographics and insurance facts from a hospital facesheet.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_first_name": {"type": "string"},
            "patient_last_name": {"type": "string"},
            "patient_dob": {"type": "string", "description": "YYYY-MM-DD"},
            "patient_mrn": {"type": "string", "description": "Medical record number"},
            "patient_address": {"type": "string"},
            "patient_phone": {"type": "string"},
            "admission_date": {"type": "string", "description": "YYYY-MM-DD"},
            "discharge_date": {"type": "string", "description": "YYYY-MM-DD if present"},
            "primary_payer_name": {"type": "string"},
            "primary_member_id": {"type": "string"},
            "primary_group_number": {"type": "string"},
            "secondary_payer_name": {"type": "string"},
            "secondary_member_id": {"type": "string"},
            "attending_physician": {"type": "string"},
            "facility_name": {"type": "string"},
            "confidence_notes": {"type": "string"},
        },
        "required": ["patient_last_name"],
        "additionalProperties": False,
    },
}


SYSTEM_PROMPT = (
    "You are a medical billing data extraction specialist. "
    "Extract structured fields from raw OCR text of insurance documents. "
    "Use null for any field not clearly present in the text. "
    "Never invent or guess member IDs or dates."
)


class LLMService:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.openai_model
        self._client: Any = None
        if _OPENAI_AVAILABLE and settings.openai_api_key:
            self._client = OpenAI(api_key=settings.openai_api_key)

    # ── Public API ────────────────────────────────────────────────────────────

    def parse_insurance_card(self, ocr_text: str, document_id: int | None = None) -> dict:
        """Extract structured fields from insurance card OCR text."""
        return self._call(
            schema=INSURANCE_CARD_SCHEMA,
            user_content=f"Extract insurance card fields from this OCR text:\n\n{ocr_text}",
            document_id=document_id,
            mode="insurance_card",
        )

    def parse_facesheet(self, ocr_text: str, document_id: int | None = None) -> dict:
        """Extract patient demographics and insurance facts from a facesheet."""
        return self._call(
            schema=FACESHEET_SCHEMA,
            user_content=f"Extract facesheet fields from this OCR text:\n\n{ocr_text}",
            document_id=document_id,
            mode="facesheet",
        )

    def classify_document(self, ocr_text: str) -> str:
        """
        Quick classification: returns INSURANCE_CARD, FACESHEET, ID_CARD, or UNKNOWN.
        Uses a simple chat call rather than a function schema.
        """
        if not self._client:
            return "UNKNOWN"

        prompt = (
            "Classify the following OCR text into exactly one of: "
            "INSURANCE_CARD, FACESHEET, ID_CARD, UNKNOWN.\n"
            "Reply with only the label.\n\n"
            f"{ocr_text[:2000]}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=16,
                temperature=0,
            )
            return resp.choices[0].message.content.strip().upper()
        except Exception as exc:
            log.warning("llm.classify_document.error", error=str(exc))
            return "UNKNOWN"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call(
        self,
        schema: dict,
        user_content: str,
        document_id: int | None,
        mode: str,
    ) -> dict:
        if not self._client:
            log.warning("llm.client_not_configured")
            return self._stub(document_id, mode)

        log.info("llm.call.start", mode=mode, document_id=document_id, model=self.model)
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content[:12000]},  # token guard
                ],
                tools=[{"type": "function", "function": schema}],
                tool_choice={"type": "function", "function": {"name": schema["name"]}},
                temperature=0,
                max_tokens=1024,
            )
            tool_call = resp.choices[0].message.tool_calls[0]
            parsed = json.loads(tool_call.function.arguments)
            parsed["document_id"] = document_id
            parsed["mode"] = mode
            parsed["confidence"] = self._estimate_confidence(parsed)
            log.info("llm.call.done", mode=mode, document_id=document_id)
            return parsed
        except Exception as exc:
            log.error("llm.call.error", mode=mode, document_id=document_id, error=str(exc))
            return self._stub(document_id, mode, error=str(exc))

    @staticmethod
    def _estimate_confidence(parsed: dict) -> float:
        """Heuristic: ratio of non-null fields to total schema fields."""
        fields = [v for k, v in parsed.items() if k not in ("document_id", "mode", "confidence_notes")]
        filled = sum(1 for v in fields if v not in (None, "", "UNKNOWN"))
        return round(filled / max(len(fields), 1), 2)

    @staticmethod
    def _stub(document_id: int | None, mode: str, error: str | None = None) -> dict:
        return {
            "document_id": document_id,
            "mode": mode,
            "member_id": None,
            "group_number": None,
            "payer_name": None,
            "confidence": 0.0,
            "_stub": True,
            "_error": error,
        }
