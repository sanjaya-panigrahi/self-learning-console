from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User question")
    session_id: str | None = Field(default=None)
    domain_context: str | None = Field(
        default=None,
        description="Optional domain or business context, e.g. operations workflow, healthcare claims",
    )


class Citation(BaseModel):
    source: str
    chunk_id: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
