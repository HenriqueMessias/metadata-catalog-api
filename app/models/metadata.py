from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Generic, TypeVar

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

PyObjectId = Annotated[str, BeforeValidator(str)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DataClassification(str, Enum):
    """LGPD-oriented sensitivity classification for a table."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"  # e.g. contains PII


class Owner(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    team: str | None = Field(default=None, max_length=120)


class ColumnSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    data_type: str = Field(..., min_length=1, max_length=60, description="e.g. STRING, INT64, TIMESTAMP")
    description: str | None = Field(default=None, max_length=500)
    nullable: bool = True
    is_pii: bool = False


class SchemaVersionEntry(BaseModel):
    """A frozen snapshot of the column layout at a point in time."""

    version: int
    columns: list[ColumnSchema]
    changed_at: datetime = Field(default_factory=utcnow)
    changed_by: str | None = None


class MetadataBase(BaseModel):
    table_name: str = Field(..., min_length=1, max_length=150)
    database_name: str = Field(..., min_length=1, max_length=150, description="Dataset/database the table lives in")
    schema_name: str = Field(default="public", min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    owner: Owner
    domain: str | None = Field(default=None, max_length=120, description="Business domain, e.g. 'finance'")
    classification: DataClassification = DataClassification.INTERNAL
    tags: list[str] = Field(default_factory=list)
    columns: list[ColumnSchema] = Field(default_factory=list)
    location: str | None = Field(default=None, description="Physical location, e.g. s3://bucket/path or project.dataset.table")


class MetadataCreate(MetadataBase):
    created_by: str | None = None


class MetadataUpdate(BaseModel):
    """All fields optional: only supplied fields are applied by the service layer."""

    description: str | None = None
    owner: Owner | None = None
    domain: str | None = None
    classification: DataClassification | None = None
    tags: list[str] | None = None
    columns: list[ColumnSchema] | None = None
    location: str | None = None
    updated_by: str | None = None


class MetadataInDB(MetadataBase):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id", default=None)
    schema_version: int = 1
    schema_history: list[SchemaVersionEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    created_by: str | None = None
    updated_by: str | None = None

    def to_mongo(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, exclude_none=False)
        if payload.get("_id") is None:
            payload.pop("_id", None)
        else:
            payload["_id"] = ObjectId(payload["_id"])
        return payload


class MetadataResponse(MetadataBase):
    id: str
    schema_version: int
    schema_history: list[SchemaVersionEntry]
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int
