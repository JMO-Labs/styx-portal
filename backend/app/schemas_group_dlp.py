from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator


class GroupDlpPut(BaseModel):
    clipboard_in: bool | None = None
    clipboard_out: bool | None = None
    upload: bool | None = None
    download: bool | None = None
    printing: bool | None = None
    watermark: bool | None = None
    approval_ref: str | None = None

    @field_validator("approval_ref")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _need_ref(self):
        if not self.approval_ref:
            raise ValueError("approval_ref is required to set a DLP override")
        return self


class GroupDlpOut(BaseModel):
    override: dict[str, bool | None]
    approval_ref: str | None
    approved_at: datetime | None
    effective: dict[str, bool]
