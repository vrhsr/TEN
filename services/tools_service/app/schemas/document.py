from pydantic import BaseModel


class DocumentCreate(BaseModel):
    clinic_id: int
    patient_id: int | None = None
    case_id: int | None = None
    document_type: str
    source_type: str
    source_ref: str | None = None
    s3_bucket: str
    s3_key: str
    mime_type: str | None = None
    sha256_hash: str | None = None
    status_code: str = "RECEIVED"
    metadata_json: dict | None = None


class DocumentOCRRequest(BaseModel):
    document_id: int
    mode: str = "insurance_card"
