"""Prompts for the writing assistant.

The single most important property here is that **the assistant must not invent
facts**. A club publishing an invented transfer fee, scoreline or appearance
count has to issue a public correction, and the trust cost lands on the club,
not on us. Every prompt is therefore built around rewriting what is already
there — never supplying what is missing.

Three mechanisms enforce that, none sufficient alone:

  1. these instructions;
  2. structured output, so the model returns typed blocks it cannot smuggle
     markup or commentary through;
  3. a side-by-side diff in the editor, so a human approves every change before
     it is saved.
"""

from __future__ import annotations

from typing import Any

from app.cms.article_types import ArticleType

# The shape the model must return. Mirrors app/cms/blocks.py — the result is
# re-validated against the Pydantic models on the way in, so this schema is the
# first gate rather than the only one.
BLOCK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["blocks", "summary_of_changes"],
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "anyOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "text"],
                        "properties": {
                            "type": {"const": "paragraph"},
                            "text": {"type": "string"},
                        },
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "level", "text"],
                        "properties": {
                            "type": {"const": "heading"},
                            "level": {"type": "integer", "enum": [2, 3]},
                            "text": {"type": "string"},
                        },
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "text"],
                        "properties": {
                            "type": {"const": "quote"},
                            "text": {"type": "string"},
                            "attribution": {"type": ["string", "null"]},
                        },
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "ordered", "items"],
                        "properties": {
                            "type": {"const": "list"},
                            "ordered": {"type": "boolean"},
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                ]
            },
        },
        "summary_of_changes": {
            "type": "string",
            "description": "One sentence describing what was changed, for the editor.",
        },
    },
}

HEADLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headlines"],
    "properties": {
        "headlines": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            # Bounded in the schema, not just the wording: an unbounded array is
            # an unbounded output-token bill on a key the platform pays for.
            "items": {"type": "string", "minLength": 1, "maxLength": 120},
            "description": "Between three and five alternative headlines.",
        }
    },
}


BASE_RULES = """\
You are a sub-editor for a football club's website. You improve the club's own \
words. You are not a journalist and you do not write copy from scratch.

Absolute rules, in order of importance:

1. Never introduce a fact that is not in the draft. No scores, dates, fees, \
ages, appearance counts, contract lengths, club names, competition names or \
attendances that the draft does not already contain. If something reads as \
incomplete, leave the gap — a missing detail is an editor's job to fill, and an \
invented one is a correction the club has to publish.
2. Never change the meaning of a sentence, and never change a number, name or \
date that is already there.
3. Never alter the wording inside a quote block. You may fix the prose around \
quotes; the quote itself is what somebody said.
4. Do not add opinion, prediction, hype or commentary of your own.
5. Keep the club's voice. This is a club talking to its own supporters, not a \
press agency. Warm, plain, specific. No marketing language.

What you should do: tighten flabby sentences, fix grammar and punctuation, \
break up walls of text, choose the concrete word over the vague one, and remove \
filler. Prefer the shorter version when both say the same thing.

Return the full article as blocks, in the same order, preserving the block types \
you were given unless merging or splitting a paragraph genuinely helps. Also \
return one sentence describing what you changed.\
"""


def polish_system_prompt(article_type: ArticleType, locale: str) -> str:
    """System prompt for the 'improve this text' operation."""
    protected = ""
    if article_type.protected_facts:
        protected = (
            "\n\nFor this kind of article, the following must never be invented, "
            "changed or implied if absent from the draft: "
            + ", ".join(article_type.protected_facts)
            + "."
        )

    return (
        f"{BASE_RULES}\n\n"
        f"This article is a {article_type.name.lower()}: "
        f"{article_type.assistant_guidance}{protected}\n\n"
        f"Write in the language of the draft ({locale}). Do not translate it."
    )


HEADLINE_RULES = """\
You write headlines for a football club's website.

Rules:
- Use only facts present in the article. Never invent a score, name or number.
- No clickbait, no questions, no puns on players' names.
- Aim for 4-9 words. Concrete beats clever.
- Write in the language of the article. Do not translate.

Return between three and five options, ordered best first.\
"""


def headline_system_prompt(article_type: ArticleType, locale: str) -> str:
    return (
        f"{HEADLINE_RULES}\n\nThis is a {article_type.name.lower()}. "
        f"The article language is {locale}."
    )


def render_draft(title: str, blocks: list[dict]) -> str:
    """Serialise the draft for the model.

    Plain labelled text rather than JSON: it keeps the model's attention on the
    prose, and the structure comes back through the output schema anyway.
    """
    lines = [f"TITLE: {title}", ""]
    for index, block in enumerate(blocks, start=1):
        kind = block.get("type")
        if kind == "heading":
            lines.append(f"[{index}] HEADING: {block.get('text', '')}")
        elif kind == "quote":
            attribution = block.get("attribution")
            suffix = f" — {attribution}" if attribution else ""
            lines.append(f"[{index}] QUOTE: {block.get('text', '')}{suffix}")
        elif kind == "list":
            items = "; ".join(block.get("items", []))
            lines.append(f"[{index}] LIST: {items}")
        else:
            lines.append(f"[{index}] PARAGRAPH: {block.get('text', '')}")
    return "\n".join(lines)
