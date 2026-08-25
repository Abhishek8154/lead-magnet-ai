import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any


class LeadStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    ENRICHED = "ENRICHED"
    VERIFIED = "VERIFIED"
    QUALIFIED = "QUALIFIED"
    SCORED = "SCORED"
    PERSONALIZED = "PERSONALIZED"
    DEMO_READY = "DEMO_READY"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    SENT = "SENT"
    DRY_RUN_SENT = "DRY_RUN_SENT"
    REPLIED = "REPLIED"
    CONVERTED = "CONVERTED"
    COLD = "COLD"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


def generate_lead_id(business_name: str, city: str = "", phone: str = "") -> str:
    """Generates a deterministic unique ID based on business_name, city, and phone."""
    b_name = (business_name or "").strip().lower()
    c_name = (city or "").strip().lower()
    p_num = (phone or "").strip().lower()
    
    raw = f"{b_name}|{c_name}|{p_num}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Lead:
    business_name: str
    category: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website_url: Optional[str] = None
    website_status: Optional[str] = None
    email: Optional[str] = None
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    lead_score: int = 0
    quality_score: int = 0
    lead_tier: Optional[str] = None
    qualification_reason: Optional[str] = None
    demo_url: Optional[str] = None
    demo_status: Optional[str] = None
    email_message: Optional[str] = None
    whatsapp_message: Optional[str] = None
    approval_status: str = "PENDING"
    email_status: str = "NOT_SENT"
    whatsapp_status: str = "NOT_SENT"
    source_url: Optional[str] = None
    raw_data: Optional[str] = None
    status: str = LeadStatus.DISCOVERED.value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_contacted_at: Optional[str] = None
    last_followup_at: Optional[str] = None
    followup_count: int = 0
    error_log: Optional[str] = None
    lead_id: str = ""

    def __post_init__(self):
        if not self.lead_id:
            self.lead_id = generate_lead_id(self.business_name, self.city or "", self.phone or "")
        if not self.lead_tier and self.lead_score is not None:
            if self.lead_score >= 70:
                self.lead_tier = "HOT"
            elif self.lead_score >= 45:
                self.lead_tier = "WARM"
            else:
                self.lead_tier = "LOW"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Lead":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
