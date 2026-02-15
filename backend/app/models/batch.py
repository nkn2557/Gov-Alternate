from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class BatchStage(str, Enum):
    COLLECTING = "collecting"
    DEDUPING = "deduping"
    STRUCTURING = "structuring"
    DONE = "done"

class UrlCandidate(BaseModel):
    id: str = Field(..., description="SHA256 of url_norm")
    url: str
    url_norm: str
    query: str
    rank: int
    title: Optional[str] = None
    snippet: Optional[str] = None
    host: str
    accepted: bool = False
    reason: Optional[str] = None
    # For deduplication phase
    title_norm: Optional[str] = None
    text_sig: Optional[List[float]] = None # Embedding vector
    created_at: datetime = Field(default_factory=lambda: datetime.now())

class ClusterConfidence(str, Enum):
    HIGH = "high"
    MID = "mid"
    LOW = "low"

class Cluster(BaseModel):
    id: str = Field(..., description="SHA256 based ID")
    primary_url: str
    member_urls: List[str]
    titles: List[str]
    confidence: ClusterConfidence
    created_at: datetime = Field(default_factory=lambda: datetime.now())
