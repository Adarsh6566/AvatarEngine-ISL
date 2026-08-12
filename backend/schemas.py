from pydantic import BaseModel, Field, field_validator

try:
    from config import get_validation_limits
except ImportError:
    from backend.config import get_validation_limits  # type: ignore[no-redef]

_min_len, _max_len = get_validation_limits()


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=_min_len, max_length=_max_len, description="English text to translate")

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be empty or whitespace")
        if len(stripped) > _max_len:
            raise ValueError(f"text must be at most {_max_len} characters")
        return stripped


class Segment(BaseModel):
    """One source word and the gestures that perform it."""

    word: str
    gestures: list[str]
    spelled: bool


class TranslateResponse(BaseModel):
    # Flat gesture ids, in order. The original contract — kept so any client
    # that only wants a playback list is unaffected.
    gloss: list[str]

    # The same gestures grouped by source word. Clients that caption playback
    # need this: it is the only thing that says which word a run of LETTER_*
    # gestures belongs to.
    segments: list[Segment]
