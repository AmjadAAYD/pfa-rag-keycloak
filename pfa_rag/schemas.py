"""Contracts for the protected retrieval and source routes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


Strategy = Literal["pre_filter", "post_filter"]


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: Annotated[str, Field(min_length=1, max_length=1500)]
    strategy: Strategy = "pre_filter"


class IdentityResponse(BaseModel):
    username: str
    roles: list[str]


class Source(BaseModel):
    document_id: str
    title: str
    url: str


class RetrievalResponse(BaseModel):
    strategy: Strategy
    sources: list[Source]


class DocumentResponse(BaseModel):
    document_id: str
    title: str
    text: str


class AnswerResponse(BaseModel):
    request_id: str
    status: Literal["answered", "insufficient_evidence"]
    strategy: Strategy
    answer: str
    citations: list[Source]
