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
    page_number: int | None = None


class ChatResponse(BaseModel):
    answer: str
    model: str = Field(default="", description="Model used to generate the answer")
    citations: list[Citation] = Field(default_factory=list)
