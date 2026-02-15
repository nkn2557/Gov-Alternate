from typing import List, Optional, Any, Dict
from enum import Enum
from pydantic import BaseModel, Field
from app.models.program import Deadline, Contact

# --- Enums ---
class RecommendationCategory(str, Enum):
    MOVING = "moving"
    BIRTH = "birth"
    EXPLORER = "explorer"  # moving + birth

# --- Request Models ---

class ChildAgeRange(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None

class UserProfile(BaseModel):
    # Flexible input mirroring frontend "generic" inputs
    household_size: Optional[int] = None
    children_counts: Optional[int] = None
    children_ages: Optional[List[int]] = None # List of ages
    children_age_ranges: Optional[List[ChildAgeRange]] = None
    couple_count: Optional[int] = None
    child_count: Optional[int] = None
    parent_count: Optional[int] = None
    adult_count: Optional[int] = None
    family_composition: Optional[str] = None
    has_disability_child: Optional[bool] = None
    has_pet: Optional[bool] = None
    is_considering_children: Optional[bool] = None
    is_pregnant: Optional[bool] = None
    expected_birth_date: Optional[str] = None # YYYY-MM
    moving_date: Optional[str] = None # YYYY-MM
    employment: Optional[str] = None
    income: Optional[int] = None
    income_t0: Optional[int] = None
    income_t1: Optional[int] = None
    # Add more as needed for MVP

class RecommendationRequest(BaseModel):
    municipality_id: str
    category: RecommendationCategory
    profile: Optional[UserProfile] = None

class ChecklistExportRequest(BaseModel):
    program_ids: List[str]


class AssistantChatRequest(BaseModel):
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    municipality: Optional[str] = None
    domain: Optional[str] = None
    profile: Optional[Dict[str, Any]] = None
    user_message: Optional[str] = None
    expect_tool_result: bool = False
    request_more: bool = False

# --- Response Models ---

class MunicipalitySearchItem(BaseModel):
    municipality_id: str
    name: str

class RecommendationCard(BaseModel):
    # Optimized for InfoScreen
    id: str # program_id
    title: str
    content: str # summary + eligibility text
    steps: List[str]
    deadline: Deadline
    official_urls: List[str]
    contact: Contact
    required_info: List[str]
    
    # Metadata for sorting/debugging
    score: Optional[float] = None
    tags: Optional[List[str]] = None

class RecommendationResponse(BaseModel):
    cards: List[RecommendationCard]
    program_count: int
    generated_at: str # ISO string

class ChecklistExportResponse(BaseModel):
    download_url: str


class AssistantChatResponse(BaseModel):
    success: bool
    session_id: str
    assistant_text: str = ""
    cards: List[Dict[str, Any]] = Field(default_factory=list)
    next_action: str = "continue"
    follow_up_questions: List[str] = Field(default_factory=list)
    events_count: int = 0
