from typing import Any

from pydantic import BaseModel, Field


class TeamRequest(BaseModel):
    offense: str = Field(min_length=2, max_length=3)
    defense: str = Field(min_length=2, max_length=3)
    user_id: int | None = None


class GameActionRequest(BaseModel):
    game_id: str = Field(min_length=36, max_length=36)


class PredictRequest(GameActionRequest):
    down: int = Field(ge=1, le=4)
    ydstogo: int = Field(ge=1, le=99)
    yardline_100: int = Field(ge=1, le=100)
    game_seconds_remaining: int = Field(ge=0, le=3600)
    qtr: int = Field(ge=1, le=5)
    score_differential: int = Field(ge=-99, le=99)
    user_id: int | None = None


class LogPlayRequest(GameActionRequest):
    actual_play_type: str
    yards_gained: float = Field(ge=-100, le=100)
    epa: float | None = None


class SignupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class SaveGameRequest(BaseModel):
    user_id: int
    title: str = Field(min_length=1, max_length=200)
    game_state: dict[str, Any]
    game_id: str | None = Field(default=None, min_length=36, max_length=36)


class LoadGameRequest(BaseModel):
    game_id: int
    user_id: int


class CheckoutSessionRequest(BaseModel):
    user_id: int
