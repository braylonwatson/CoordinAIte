from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeamRequest(StrictRequest):
    offense: str = Field(min_length=2, max_length=3)
    defense: str = Field(min_length=2, max_length=3)


class GameActionRequest(StrictRequest):
    game_id: str = Field(min_length=36, max_length=36)


class PredictRequest(GameActionRequest):
    down: int = Field(ge=1, le=4)
    ydstogo: int = Field(ge=1, le=99)
    yardline_100: int = Field(ge=1, le=100)
    game_seconds_remaining: int = Field(ge=0, le=3600)
    qtr: int = Field(ge=1, le=5)
    score_differential: int = Field(ge=-99, le=99)


class LogPlayRequest(GameActionRequest):
    actual_play_type: str
    yards_gained: float = Field(ge=-100, le=100)
    epa: float | None = None


class SignupRequest(StrictRequest):
    username: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def nonblank_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username cannot be blank")
        return value


class LoginRequest(StrictRequest):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class SaveGameRequest(StrictRequest):
    title: str = Field(min_length=1, max_length=200)
    game_state: dict[str, Any]
    game_id: str = Field(min_length=36, max_length=36)


class LoadGameRequest(StrictRequest):
    game_id: int = Field(gt=0)


class CheckoutSessionRequest(StrictRequest):
    pass
