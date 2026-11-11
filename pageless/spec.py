"""The page spec: the model's output format, an ordered list of steps."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

SectionId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]
ComponentName = Annotated[str, StringConstraints(max_length=40)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutlineSection(_Strict):
    id: SectionId
    component: ComponentName
    span: int = Field(ge=1)


class OutlineStep(_Strict):
    type: Literal["outline"]
    sections: list[OutlineSection] = Field(min_length=1, max_length=12)


class AddStep(_Strict):
    type: Literal["add"]
    id: SectionId
    component: ComponentName | None = None
    span: int | None = Field(default=None, ge=1)
    props: dict = Field(default_factory=dict)


class MoveStep(_Strict):
    type: Literal["move"]
    id: SectionId
    span: int | None = Field(default=None, ge=1)
    order: int | None = Field(default=None, ge=0)


Step = Annotated[OutlineStep | AddStep | MoveStep, Field(discriminator="type")]
STEP_ADAPTER: TypeAdapter[Step] = TypeAdapter(Step)


class PageSpec(_Strict):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    steps: list[Step]
