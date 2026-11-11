"""The component catalog: the only things a page may contain, with strict prop schemas."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CATALOG_VERSION = 1

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ItemId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]
RoutePath = Annotated[str, StringConstraints(pattern=r"^/[a-z0-9/_-]{0,199}$")]
Url = Annotated[str, StringConstraints(max_length=500)]


class Props(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HeroProps(Props):
    heading: ShortText
    contentId: ItemId
    subheading: ShortText | None = None


class RichTextProps(Props):
    heading: ShortText | None = None
    contentIds: list[ItemId] = Field(min_length=1, max_length=4)


class TimelineProps(Props):
    heading: ShortText | None = None
    contentIds: list[ItemId] = Field(min_length=1, max_length=12)


class ProjectCardProps(Props):
    contentId: ItemId


class CardGridProps(Props):
    heading: ShortText | None = None
    contentIds: list[ItemId] = Field(min_length=1, max_length=9)


class GalleryProps(Props):
    heading: ShortText | None = None
    assetIds: list[ItemId] = Field(min_length=1, max_length=12)


class LinkListProps(Props):
    heading: ShortText | None = None
    routes: list[RoutePath] = Field(default_factory=list, max_length=8)
    urls: list[Url] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.routes and not self.urls:
            raise ValueError("LinkList needs at least one route or url")
        return self


class ContactBlockProps(Props):
    heading: ShortText | None = None
    contentId: ItemId | None = None


@dataclass(frozen=True)
class Component:
    name: str
    props: type[Props]
    # Content item types allowed in contentId/contentIds; empty means any type.
    content_types: tuple[str, ...] = ()
    # Model-written text fields: escaped, cleaned and length-capped.
    text_fields: tuple[str, ...] = ("heading",)
    description: str = ""
    # Whether the component needs content of its types (or assets) to be usable on a page.
    needs: str = "items"  # "items" | "assets" | "none"


CATALOG: dict[str, Component] = {
    c.name: c
    for c in [
        Component("Hero", HeroProps, text_fields=("heading", "subheading"),
                  description="Page opener: a short heading plus one item's text."),
        Component("RichText", RichTextProps, description="One to four items shown as prose."),
        Component("Timeline", TimelineProps, content_types=("experience", "education"),
                  description="Experience and education in date order."),
        Component("ProjectCard", ProjectCardProps, content_types=("project", "writing"), text_fields=(),
                  description="A single highlighted project."),
        Component("CardGrid", CardGridProps, content_types=("project", "writing"),
                  description="A grid of project or writing cards."),
        Component("Gallery", GalleryProps, description="Images from the retrieved assets.", needs="assets"),
        Component("LinkList", LinkListProps, description="Links to site routes or approved external URLs.", needs="none"),
        Component("ContactBlock", ContactBlockProps, content_types=("contact",),
                  description="Contact details and the owner's required links.", needs="none"),
    ]
}
