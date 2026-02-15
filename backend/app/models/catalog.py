from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel

from app.models.batch import BatchStage

class CatalogStatus(str, Enum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"

class Catalog(BaseModel):
    id: Optional[str] = None
    municipality_id: str
    municipality_name: Optional[str] = None # Added for convenience
    domain: str
    status: CatalogStatus
    stage: Optional[BatchStage] = None
    build_started_at: datetime
    build_finished_at: Optional[datetime] = None
    stats: Optional[Dict[str, Any]] = None

class CatalogPointer(BaseModel):
    current_catalog_id: str
    updated_at: datetime
