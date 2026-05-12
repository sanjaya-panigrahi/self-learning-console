from pydantic import BaseModel, Field


class PiiApprovalRequest(BaseModel):
    file: str = Field(..., min_length=1)
    approved_by: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=3)


class RetrievalSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    domain_context: str | None = Field(default=None)
    top_k: int = Field(default=6, ge=1, le=12)
    orchestrator: str | None = Field(default=None)


class MaterialInsightRequest(BaseModel):
    source: str = Field(..., min_length=1)
    domain_context: str | None = Field(default=None)
    use_cache: bool = Field(default=True)


class FeedbackRecordRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    helpful: bool
    query: str | None = None
    retrieval_query: str | None = None
    answer_model: str | None = None
    answer_confidence: float | None = None
    result_count: int | None = Field(default=None, ge=0)
    sources: list[str] = Field(default_factory=list)
    comment: str | None = None
    answer: str | None = None


class WarmCacheRunRequest(BaseModel):
    force: bool = False


class BenchmarkRunRequest(BaseModel):
    max_cases: int = Field(default=8, ge=1, le=50)


class DeployIntelligenceRunRequest(BaseModel):
    force: bool = False
    blocking: bool = False


class FileAnswerRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list)
    session_id: str | None = Field(default=None)


class WikiReviewUpdateRequest(BaseModel):
    kind: str = Field(..., pattern="^(source|entity|concept|answer)$")
    name: str = Field(..., min_length=1)
    status: str = Field(..., pattern="^(draft|reviewed|approved)$")
    reviewer: str | None = Field(default=None)
    notes: str | None = Field(default=None)
