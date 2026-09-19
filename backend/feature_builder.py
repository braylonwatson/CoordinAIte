from functools import lru_cache

import numpy as np
import pandas as pd


def safe_rate(passes: int, plays: int, default: float = 0.5) -> float:
    # Bayesian smoothing to prevent extreme early values
    if plays < 0:
        return default
    return (passes + 1) / (plays + 2)


def build_situational_flags(
    down: int,
    ydstogo: int,
    yardline_100: int,
    game_seconds_remaining: int,
    qtr: int,
    score_differential: int
) -> dict:
    is_third_down = 1 if down == 3 else 0
    is_fourth_down = 1 if down == 4 else 0

    short_yardage = 1 if ydstogo <= 2 else 0
    medium_yardage = 1 if 3 <= ydstogo <= 6 else 0
    long_yardage = 1 if ydstogo >= 7 else 0

    red_zone = 1 if yardline_100 <= 20 else 0
    goal_to_go = 1 if yardline_100 <= 10 and ydstogo >= yardline_100 else 0
    backed_up = 1 if yardline_100 >= 90 else 0
    plus_territory = 1 if yardline_100 <= 50 else 0

    two_minute = 1 if qtr in [2, 4] and game_seconds_remaining <= 120 else 0
    leading_team = 1 if score_differential > 0 else 0
    trailing_team = 1 if score_differential < 0 else 0
    neutral_score = 1 if score_differential == 0 else 0

    return {
        "is_third_down": is_third_down,
        "is_fourth_down": is_fourth_down,
        "short_yardage": short_yardage,
        "medium_yardage": medium_yardage,
        "long_yardage": long_yardage,
        "red_zone": red_zone,
        "goal_to_go": goal_to_go,
        "backed_up": backed_up,
        "plus_territory": plus_territory,
        "two_minute": two_minute,
        "leading_team": leading_team,
        "trailing_team": trailing_team,
        "neutral_score": neutral_score,
    }


def build_feature_values(
    down: int,
    ydstogo: int,
    yardline_100: int,
    game_seconds_remaining: int,
    qtr: int,
    score_differential: int,
    posteam: str,
    defteam: str,
    prev_play_pass: int,
    game_pass_rate: float,
    drive_pass_rate: float
) -> dict:
    row = {
        "down": down,
        "ydstogo": ydstogo,
        "yardline_100": yardline_100,
        "game_seconds_remaining": game_seconds_remaining,
        "qtr": qtr,
        "score_differential": score_differential,
        "posteam": posteam,
        "defteam": defteam,
        "prev_play_pass": prev_play_pass,
        "game_pass_rate": game_pass_rate,
        "drive_pass_rate": drive_pass_rate,
    }

    row.update(
        build_situational_flags(
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            game_seconds_remaining=game_seconds_remaining,
            qtr=qtr,
            score_differential=score_differential,
        )
    )

    return row


def build_feature_row(*args, **kwargs) -> pd.DataFrame:
    """Compatibility helper for offline consumers; inference uses numeric arrays."""
    return pd.DataFrame([build_feature_values(*args, **kwargs)])


@lru_cache(maxsize=16)
def _column_plan(columns: tuple[str, ...]):
    if len(set(columns)) != len(columns):
        raise ValueError("Model feature columns must be unique")
    return tuple(
        (name, "posteam", name[len("posteam_"):]) if name.startswith("posteam_")
        else (name, "defteam", name[len("defteam_"):]) if name.startswith("defteam_")
        else (name, None, None)
        for name in columns
    )


def encode_feature_values(values: dict, columns) -> np.ndarray:
    """Match the saved training schema, including its dropped baseline teams.

    Never fit one-hot encoding to one request: drop_first on a one-row frame
    drops both team indicators. Each call owns its buffer for thread safety.
    Missing numeric features retain the historical reindex(fill_value=0) rule.
    """
    plan = _column_plan(tuple(columns))
    return np.fromiter(
        (float(values.get(field) == category) if field else float(values.get(name, 0))
         for name, field, category in plan),
        dtype=np.float32, count=len(plan),
    ).reshape(1, len(plan))
