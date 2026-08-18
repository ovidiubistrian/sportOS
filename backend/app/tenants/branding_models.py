from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped

# How a club shows a team sheet. Not a cosmetic choice: the provider gives
# positions only for the leagues it covers fully, so a club in a division it
# does not cover has names and shirt numbers and nothing else. `LIST` is
# always honest; `PITCH` is better when somebody has arranged the eleven, and
# falls back to a list on its own when nobody has.
LINEUP_DISPLAYS = ("LIST", "PITCH")

# A closed set. Clubs choose a template; they cannot supply one, and there is
# no mechanism for arbitrary CSS. That constraint is what lets sixty screens
# built over two years still look like one product (doc 14 §8).
SITE_TEMPLATES = ("CLASSIC", "BOLD", "COMPACT", "EDITORIAL")
COLOR_MODES = ("LIGHT", "DARK", "AUTO")


class ClubBranding(Base, Timestamped, TenantScoped):
    """How one club's public site and admin shell are themed.

    One row per club, created with the club. Colours are stored exactly as the
    club chose them; the readable variants are derived on read
    (`app/tenants/colors.py`) rather than stored, so improving the contrast
    maths fixes every tenant at once instead of requiring a backfill.
    """

    __tablename__ = "club_branding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_club_branding_club",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "template IN " + str(SITE_TEMPLATES), name="club_branding_template_valid"
        ),
        CheckConstraint(
            "lineup_display IN " + str(LINEUP_DISPLAYS),
            name="lineup_display_valid",
        ),
        CheckConstraint(
            "color_mode IN " + str(COLOR_MODES), name="club_branding_color_mode_valid"
        ),
        CheckConstraint(
            "color_primary ~ '^#[0-9A-F]{6}$'", name="club_branding_primary_is_hex"
        ),
        ForeignKeyConstraint(
            ["crest_media_id"],
            ["media_asset.id"],
            name="fk_branding_crest",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["hero_media_id"],
            ["media_asset.id"],
            name="fk_branding_hero",
            ondelete="SET NULL",
        ),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    template: Mapped[str] = mapped_column(String(16), default="CLASSIC")

    # Defaults to the list, because that is what every club can show from the
    # provider alone. A club that arranges its eleven turns on the pitch.
    lineup_display: Mapped[str] = mapped_column(String(8), default="LIST")
    color_mode: Mapped[str] = mapped_column(String(8), default="LIGHT")

    color_primary: Mapped[str] = mapped_column(String(7), default="#1F4B99")
    color_secondary: Mapped[str | None] = mapped_column(String(7))
    color_accent: Mapped[str | None] = mapped_column(String(7))

    tagline: Mapped[str | None] = mapped_column(String(160))
    social: Mapped[dict] = mapped_column(JSONB, default=dict)

    # The asset id, not the URL. Storing the URL would leave a club's home page
    # pointing at a deleted object; the foreign key nulls the reference instead,
    # so the worst case is a missing crest rather than a broken image.
    crest_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    hero_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    # The strip above the fixtures: whatever the club needs to say this week.
    # Off by default — a club with nothing to announce should not have an empty
    # banner on its home page.
    announcement_text: Mapped[str | None] = mapped_column(String(300))
    announcement_is_active: Mapped[bool] = mapped_column(default=False)

    # Where supporters buy. External for now — most clubs already sell
    # somewhere. When ticketing lands the target changes, not the button.
    tickets_url: Mapped[str | None] = mapped_column(String(500))
    tickets_label: Mapped[str | None] = mapped_column(String(48))

    # --- the footer ---------------------------------------------------------
    #
    # Every club's footer says the same kinds of thing and none of them the same
    # way: a village club has a phone number and a Facebook page, a Liga II club
    # has a registered address, four sponsors and a VAT number. So it is
    # configuration rather than a template decision, and a club that fills none
    # of it gets a footer with just its name — which is what it has now.
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    # Free text, not parsed. An address is a local format, and a club that
    # writes it as four lines should see four lines.
    address: Mapped[str | None] = mapped_column(Text)
    # Company registration, VAT number, the line a Romanian club is required to
    # print. Nobody but the club knows what belongs here.
    legal_line: Mapped[str | None] = mapped_column(String(300))

    # `[{"name": ..., "url": ..., "media_id": ...}]`. JSON rather than a table
    # because a sponsor here is a name and a logo, not an entity with a life of
    # its own — and because a club reorders them by dragging, which is a list
    # operation. The media id inside JSON has no foreign key, so the reader
    # resolves what still exists and silently drops what does not.
    sponsors: Mapped[list] = mapped_column(JSONB, default=list)
    sponsors_title: Mapped[str | None] = mapped_column(String(80))

    updated_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
