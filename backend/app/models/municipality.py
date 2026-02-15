from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

class Municipality(BaseModel):
    id: str  # e.g., tokyo-chiyoda
    name: str
    enabled: bool = True

class SourceUrls(BaseModel):
    urls: List[str]
    updated_at: datetime
