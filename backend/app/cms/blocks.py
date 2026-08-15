"""Content blocks.

A body is a list of typed blocks rather than HTML. That buys two things:

  * **Four templates, one body.** Each site template renders a quote or a list
    in its own character; an HTML blob would force every template to look the
    same, or to parse and re-style someone else's markup.
  * **Stored XSS is unrepresentable.** Blocks carry text, and the templates
    render text nodes. There is no path from stored content to executable
    markup, so there is nothing to sanitise and nothing to get wrong later.

The block set is deliberately small. A club needs to publish match reports and
announcements, not build landing pages.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Text = Annotated[str, StringConstraints(min_length=1, max_length=5000, strip_whitespace=True)]
ShortText = Annotated[
    str, StringConstraints(min_length=1, max_length=300, strip_whitespace=True)
]


class Paragraph(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    text: Text


class Heading(BaseModel):
    type: Literal["heading"] = "heading"
    # h1 belongs to the page title, so body headings start at h2.
    level: Literal[2, 3] = 2
    text: ShortText


class Quote(BaseModel):
    type: Literal["quote"] = "quote"
    text: Text
    attribution: ShortText | None = None


class ListBlock(BaseModel):
    type: Literal["list"] = "list"
    ordered: bool = False
    items: list[ShortText] = Field(min_length=1, max_length=50)


Block = Annotated[Paragraph | Heading | Quote | ListBlock, Field(discriminator="type")]

MAX_BLOCKS = 200


class Body(BaseModel):
    """Validation wrapper; stored as a plain JSON array."""

    blocks: list[Block] = Field(default_factory=list, max_length=MAX_BLOCKS)


def validate_body(raw: list[dict] | None) -> list[dict]:
    """Parse and normalise a body, rejecting anything not in the block set."""
    parsed = Body(blocks=raw or [])
    return [block.model_dump() for block in parsed.blocks]


def plain_text(blocks: list[dict] | None, limit: int = 300) -> str:
    """Flatten a body to text, for excerpts and search."""
    parts: list[str] = []
    for block in blocks or []:
        if "text" in block:
            parts.append(str(block["text"]))
        elif block.get("type") == "list":
            parts.extend(str(item) for item in block.get("items", []))
    joined = " ".join(parts).strip()
    if len(joined) <= limit:
        return joined
    return joined[: limit - 1].rsplit(" ", 1)[0] + "…"
