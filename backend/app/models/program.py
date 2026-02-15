from typing import List, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime

class DeadlineType(str, Enum):
    WITHIN_DAYS = "within_days"
    BY_DATE = "by_date"
    NONE = "none"
    UNKNOWN = "unknown"

class ProgramKind(str, Enum):
    PROCEDURE = "procedure"
    CASH_BENEFIT = "cash_benefit"
    SUBSIDY_REIMBURSEMENT = "subsidy_reimbursement"
    VOUCHER_COUPON = "voucher_coupon"
    FEE_REDUCTION_EXEMPTION = "fee_reduction_exemption"
    CONSULTATION_SUPPORT = "consultation_support"

class ProgramAction(str, Enum):
    REPORT = "report"
    APPLY = "apply"
    CHANGE = "change"
    REGISTER = "register"
    USE = "use"
    BOOK = "book"

class ProgramImportance(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

class LifeEventTag(str, Enum):
    # Moving
    MOVING_OUT = "moving_out"
    MOVING_IN = "moving_in"
    MOVING_WITHIN = "moving_within"
    MYNUMBER_CHANGE = "mynumber_change"
    CHILDCARE_ADDRESS_CHANGE = "childcare_address_change"
    # Childcare
    PREGNANCY = "pregnancy"
    BIRTH = "birth"
    NEWBORN = "newborn"
    AGE_0_2 = "age_0_2"
    AGE_3_5 = "age_3_5"
    PRESCHOOL = "preschool"
    HEALTH_CHECKUP = "health_checkup"
    VACCINATION = "vaccination"
    CHILD_ALLOWANCE = "child_allowance"
    MEDICAL_SUBSIDY = "medical_subsidy"
    CHILDCARE_APPLICATION = "childcare_application"

class Contact(BaseModel):
    name: Optional[str] = None
    tel: Optional[str] = None
    url: Optional[str] = None

class Deadline(BaseModel):
    type: DeadlineType
    value: Optional[Any] = None  # number or string date
    note: Optional[str] = None

class Source(BaseModel):
    retrieved_at: datetime
    source_title: Optional[str] = None


class ProgramEligibility(BaseModel):
    # Optional structured eligibility used for recommendation pre-filtering.
    requires_moving: Optional[bool] = None
    requires_pregnancy: Optional[bool] = None
    requires_children: Optional[bool] = None
    requires_disability_child: Optional[bool] = None
    requires_single_parent: Optional[bool] = None
    child_count_min: Optional[int] = None
    child_count_max: Optional[int] = None
    child_age_min: Optional[int] = None
    child_age_max: Optional[int] = None
    household_size_min: Optional[int] = None
    household_size_max: Optional[int] = None
    income_min: Optional[int] = None
    income_max: Optional[int] = None
    applicable_employment: List[str] = Field(default_factory=list)
    is_mandatory: Optional[bool] = None


class Program(BaseModel):
    municipality_id: str
    domain: str
    canonical_key: str
    title_official: str
    title_common: str
    summary: str
    steps: List[str]
    kind: ProgramKind
    actions: List[ProgramAction]
    importance: ProgramImportance = ProgramImportance.UNKNOWN
    life_event_tags: List[LifeEventTag]
    official_urls: List[str]
    contact: Contact
    deadline: Deadline
    eligibility_text: str
    eligibility_profile: Optional[ProgramEligibility] = None
    # Estimated prevalence (0-100): how many people out of 100 likely need this.
    need_prevalence_score: Optional[float] = None
    required_info: List[str]
    source: Source
