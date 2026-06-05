# Shared dataclasses and enums used across the classification pipeline.
# Kept in a separate file to avoid circular imports between extractor and validator.

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class EmailCategory(str, enum.Enum):
    APPLICATION_CONFIRMATION = "APPLICATION_CONFIRMATION"
    INTERVIEW_INVITATION     = "INTERVIEW_INVITATION"
    JOB_OFFER                = "JOB_OFFER"
    REJECTION                = "REJECTION"
    STATUS_UPDATE            = "STATUS_UPDATE"
    IRRELEVANT               = "IRRELEVANT"


@dataclass
class ExtractedData:
    """Fully-validated, normalised data extracted from a job email."""
    email_id:                str
    email_subject:           str
    email_date:              datetime
    email_sender:            str
    category:                str           # EmailCategory value
    company:                 str
    role:                    str
    platform:                str           # Platform enum value
    job_url:                 Optional[str]
    location:                Optional[str]
    salary_range:            Optional[str]
    job_description_snippet: Optional[str]
    confidence:              float          # 0.0 – 1.0
