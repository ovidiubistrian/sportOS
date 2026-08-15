"""Article types.

A club newsroom writes the same handful of things over and over: a match
report, a signing, a departure, a fixture preview. Naming those types buys
three things at once:

  * a **starter skeleton**, so an editor faces a structure rather than a blank
    page;
  * **context for the writing assistant** — "polish this" is a much better
    instruction when the model knows it is polishing a farewell to a departing
    player rather than a cup draw;
  * **structure for the newsroom** — the admin list and the public site can
    group and filter by type.

Types are a closed set, like site templates. A club picks one; it cannot invent
one, because every type carries prompt and layout behaviour that has to exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ARTICLE_TYPES = (
    "ANNOUNCEMENT",
    "MATCH_REPORT",
    "MATCH_PREVIEW",
    "SIGNING",
    "DEPARTURE",
    "ACADEMY",
    "INTERVIEW",
)


@dataclass(frozen=True, slots=True)
class ArticleType:
    key: str
    name: str
    description: str
    # Prefilled body. Placeholder text is deliberately a *prompt to the editor*
    # ("Who, from where, on what terms") rather than lorem — an editor should
    # never be able to publish the skeleton by accident and have it read as
    # finished copy.
    skeleton: list[dict] = field(default_factory=list)
    # Appended to the writing assistant's system prompt.
    assistant_guidance: str = ""
    # Facts the assistant must never invent for this type. These are the ones
    # that cause real damage: a fabricated transfer fee or scoreline is a
    # correction the club has to issue publicly.
    protected_facts: tuple[str, ...] = ()


def _p(text: str) -> dict:
    return {"type": "paragraph", "text": text}


def _h(text: str) -> dict:
    return {"type": "heading", "level": 2, "text": text}


TYPES: tuple[ArticleType, ...] = (
    ArticleType(
        key="ANNOUNCEMENT",
        name="Announcement",
        description="General club news: facilities, partnerships, schedules.",
        skeleton=[_p("What is happening, and when.")],
        assistant_guidance=(
            "This is a general club announcement. Lead with what is happening "
            "and when. Keep it factual and short."
        ),
        protected_facts=("dates", "times", "prices", "names"),
    ),
    ArticleType(
        key="MATCH_REPORT",
        name="Match report",
        description="What happened in a match that has been played.",
        skeleton=[
            _p("The result, and the one thing that decided it."),
            _h("How it unfolded"),
            _p("The passage of play that mattered."),
            _p("What it means for the season."),
        ],
        assistant_guidance=(
            "This is a report on a match that has already been played. Write in "
            "the past tense. Lead with the result. Never invent a scoreline, a "
            "scorer, a minute, an attendance figure or a quote — if the draft "
            "does not contain one, leave it out rather than filling the gap."
        ),
        protected_facts=("score", "scorers", "minutes", "attendance", "opponent"),
    ),
    ArticleType(
        key="MATCH_PREVIEW",
        name="Match preview",
        description="Ahead of a fixture: team news, context, ticket details.",
        skeleton=[
            _p("Who we play, where, and when."),
            _h("Team news"),
            _p("Availability and selection."),
        ],
        assistant_guidance=(
            "This previews a fixture that has not been played. Write in the "
            "future tense and never predict a result as though it were fact. "
            "Do not invent kick-off times, ticket prices or injury news."
        ),
        protected_facts=("kick-off time", "venue", "ticket prices", "injuries"),
    ),
    ArticleType(
        key="SIGNING",
        name="New signing",
        description="Welcoming a player who has joined the club.",
        skeleton=[
            _p("Who has signed, from where, and for how long."),
            _h("What they bring"),
            _p("Position, style, what the coaching staff expect."),
            {
                "type": "quote",
                "text": "A quote from the player or coach.",
                "attribution": "Name, role",
            },
        ],
        assistant_guidance=(
            "This announces a player joining the club. The tone is warm and "
            "welcoming but factual. Never invent a transfer fee, contract "
            "length, previous club, age or honours — a fabricated fee is a "
            "correction the club has to publish. If the draft does not state a "
            "term, do not imply one."
        ),
        protected_facts=("fee", "contract length", "previous club", "age", "honours"),
    ),
    ArticleType(
        key="DEPARTURE",
        name="Player departure",
        description="A player leaving, with thanks for their time at the club.",
        skeleton=[
            _p("Who is leaving, and where they are going if it is known."),
            _h("Thank you"),
            _p("What they gave the club: years, appearances, moments."),
            _p("The club wishes them well."),
        ],
        assistant_guidance=(
            "This marks a player leaving the club. The tone is grateful and "
            "generous — this is a farewell, not a transaction notice. Never "
            "invent appearance counts, goal tallies, years of service, a "
            "destination club or a fee. Never imply the departure was "
            "acrimonious, and never speculate about the reason for it."
        ),
        protected_facts=(
            "appearances",
            "goals",
            "years at the club",
            "destination",
            "fee",
            "reason for leaving",
        ),
    ),
    ArticleType(
        key="ACADEMY",
        name="Academy news",
        description="Academy results, trials, registrations, player progress.",
        skeleton=[
            _p("What the academy news is."),
            _p("Who it affects and what parents need to do."),
        ],
        assistant_guidance=(
            "This is academy news, read mostly by parents. Be clear about what "
            "action a parent needs to take and by when. Never name a player "
            "under 16 in a way the draft does not already, and never invent "
            "trial dates, fees or age-group criteria."
        ),
        protected_facts=("dates", "fees", "age groups", "player names"),
    ),
    ArticleType(
        key="INTERVIEW",
        name="Interview",
        description="A conversation with a player, coach or staff member.",
        skeleton=[
            _p("Who this is with, and why now."),
            {"type": "quote", "text": "Their answer.", "attribution": "Name, role"},
        ],
        assistant_guidance=(
            "This is an interview. Quotes are sacred: never alter the wording "
            "inside a quote block, never invent a quote, and never attribute a "
            "quote to someone the draft does not name. You may improve the "
            "prose around the quotes."
        ),
        protected_facts=("quotes", "attribution"),
    ),
)

BY_KEY = {t.key: t for t in TYPES}
DEFAULT_TYPE = "ANNOUNCEMENT"


def get_type(key: str | None) -> ArticleType:
    return BY_KEY.get(key or DEFAULT_TYPE, BY_KEY[DEFAULT_TYPE])
