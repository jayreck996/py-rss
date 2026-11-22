from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class Image(BaseModel):
    url: str
    alt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class Article(BaseModel):
    url: str
    source: str = "nintendo"
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    summary: Optional[str] = None
    cover_image: Optional[Image] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    images: list[Image] = []
    tags: list[str] = []
