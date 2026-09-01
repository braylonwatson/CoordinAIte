from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import joblib
import pandas as pd
from pathlib import Path

from feature_builder import build_feature_row, safe_rate
from recommendation_engine import get_confidence_tier


BASE_DIR = Path(__file__).resolve().parent


def _load_pickle(filename: str):
    return joblib.load(BASE_DIR / filename)


def load_model_bundle(model_filename: str, columns_filename: str):
    model = _load_pickle(model_filename)
    model_columns = _load_pickle(columns_filename)
    return model, model_columns


def load_optional_model_bundle(model_filename: str, columns_filename: str):
    model_path = BASE_DIR / model_filename
    cols_path = BASE_DIR / columns_filename

    if not model_path.exists() or not cols_path.exists():
        return None, None

    return _load_pickle(model_filename), _load_pickle(columns_filename)


@dataclass(frozen=True)
class ModelBundle:
    """Immutable model references that can be shared by every request."""

    model: Any
    model_columns: list[str]
    direction_model: Any | None = None
    direction_model_columns: list[str] | None = None
    run_concept_model: Any | None = None
    run_concept_model_columns: list[str] | None = None
    pass_concept_model: Any | None = None
    pass_concept_model_columns: list[str] | None = None

    @classmethod
    def load(cls) -> "ModelBundle":
        model, model_columns = load_model_bundle(
            "play_predictor_model.pkl",
            "model_columns.pkl",
        )
        direction_model, direction_columns = load_optional_model_bundle(
            "direction_predictor_model.pkl",
            "direction_model_columns.pkl",
        )
        run_model, run_columns = load_optional_model_bundle(
            "run_concept_predictor_model.pkl",
            "run_concept_model_columns.pkl",
        )
        pass_model, pass_columns = load_optional_model_bundle(
            "pass_concept_predictor_model.pkl",
            "pass_concept_model_columns.pkl",
        )
        return cls(
            model=model,
            model_columns=model_columns,
            direction_model=direction_model,
            direction_model_columns=direction_columns,
            run_concept_model=run_model,
            run_concept_model_columns=run_columns,
            pass_concept_model=pass_model,
            pass_concept_model_columns=pass_columns,
        )

    def tier2_available(self) -> bool:
        return all(
            value is not None
            for value in (
                self.direction_model,
                self.direction_model_columns,
                self.run_concept_model,
                self.run_concept_model_columns,
                self.pass_concept_model,
                self.pass_concept_model_columns,
            )
        )


def get_defensive_strategy(
    prediction: str,
    run_prob: float,
    pass_prob: float,
    down: int,
    ydstogo: int,
    yardline_100: int,
    score_differential: int,
    confidence_tier: str,
    situational_snapshot: dict | None = None,
):
    short_yardage = ydstogo <= 2
    medium_yardage = 3 <= ydstogo <= 6
    long_yardage = (
        (down == 1 and ydstogo >= 11)
        or (down == 2 and ydstogo >= 8)
        or (down in [3, 4] and ydstogo >= 7)
    )
    red_zone = yardline_100 <= 20
    backed_up = yardline_100 >= 90

    situation_notes = []
    pass_rate_signals = []

    if situational_snapshot:
        for key, stats in situational_snapshot.items():
            if stats["plays"] > 0:
                rate = stats["pass_rate"]
                pass_rate_signals.append(rate)
                situation_notes.append(
                    f"{key} pass_rate={rate:.3f} ({stats['passes']}/{stats['plays']})"
                )

    live_pass_rate = None
    if pass_rate_signals:
        live_pass_rate = sum(pass_rate_signals) / len(pass_rate_signals)

    if live_pass_rate is not None:
        blended_pass_prob = (0.7 * pass_prob) + (0.3 * live_pass_rate)
    else:
        blended_pass_prob = pass_prob

    blended_run_prob = 1 - blended_pass_prob
    blended_prediction = "PASS" if blended_pass_prob >= 0.5 else "RUN"

    tendency_conflict = False
    if live_pass_rate is not None:
        if prediction == "RUN" and live_pass_rate >= 0.65:
            tendency_conflict = True
        elif prediction == "PASS" and live_pass_rate <= 0.35:
            tendency_conflict = True

    softened = False
    if confidence_tier in ["WEAK", "NEUTRAL"] or tendency_conflict:
        softened = True

    if confidence_tier == "NEUTRAL":
        return {
            "defensive_personnel": "Match offense",
            "front": "Balanced front",
            "coverage_shell": "Neutral shell",
            "pressure": "Standard rush",
            "aggression": "Conservative",
            "primary_focus": "Stay structurally sound",
            "reason": "Prediction confidence is low, so avoid overcommitting.",
            "situation_notes": situation_notes,
            "blended_pass_probability": round(blended_pass_prob, 3),
            "blended_run_probability": round(blended_run_prob, 3),
        }

    if blended_prediction == "RUN":
        if short_yardage:
            if softened:
                return {
                    "defensive_personnel": "Base / Big Nickel",
                    "front": "Firm box, not all-in",
                    "coverage_shell": "Single-high with play-action awareness",
                    "pressure": "Controlled pressure",
                    "aggression": "Balanced",
                    "primary_focus": "Defend short-yardage run while respecting quick pass",
                    "reason": (
                        f"Blended run lean is {blended_run_prob:.1%}. "
                        f"Model and/or live tendency suggest some pass risk, so do not fully sell out."
                    ),
                    "situation_notes": situation_notes,
                    "blended_pass_probability": round(blended_pass_prob, 3),
                    "blended_run_probability": round(blended_run_prob, 3),
                }

            return {
                "defensive_personnel": "Base / Heavy",
                "front": "Heavy box",
                "coverage_shell": "Single-high",
                "pressure": "Run pressure optional",
                "aggression": "Aggressive",
                "primary_focus": "Defend interior run / short conversion",
                "reason": f"Blended run probability is {blended_run_prob:.1%} in a short-yardage situation.",
                "situation_notes": situation_notes,
                "blended_pass_probability": round(blended_pass_prob, 3),
                "blended_run_probability": round(blended_run_prob, 3),
            }

        if red_zone:
            if softened:
                return {
                    "defensive_personnel": "Base / Big Nickel",
                    "front": "Compact front",
                    "coverage_shell": "Single-high or matchup zone",
                    "pressure": "Controlled pressure",
                    "aggression": "Balanced",
                    "primary_focus": "Close run lanes but stay alert for quick pass/play-action",
                    "reason": (
                        f"Blended run lean is {blended_run_prob:.1%}, "
                        f"but live situational tendency raises pass risk."
                    ),
                    "situation_notes": situation_notes,
                    "blended_pass_probability": round(blended_pass_prob, 3),
                    "blended_run_probability": round(blended_run_prob, 3),
                }

            return {
                "defensive_personnel": "Base / Big Nickel",
                "front": "Compact front",
                "coverage_shell": "Single-high or matchup zone",
                "pressure": "Controlled pressure",
                "aggression": "Balanced",
                "primary_focus": "Close run lanes and watch play-action",
                "reason": f"Blended run probability is {blended_run_prob:.1%} in the red zone.",
                "situation_notes": situation_notes,
                "blended_pass_probability": round(blended_pass_prob, 3),
                "blended_run_probability": round(blended_run_prob, 3),
            }

        if backed_up:
            return {
                "defensive_personnel": "Base",
                "front": "Attack front",
                "coverage_shell": "Single-high",
                "pressure": "Run pressure optional",
                "aggression": "Aggressive",
                "primary_focus": "Force run into a crowded box and win field position",
                "reason": f"Blended run probability is {blended_run_prob:.1%} while offense is backed up.",
                "situation_notes": situation_notes,
                "blended_pass_probability": round(blended_pass_prob, 3),
                "blended_run_probability": round(blended_run_prob, 3),
            }

        if softened:
            return {
                "defensive_personnel": "Base / Big Nickel",
                "front": "Balanced front",
                "coverage_shell": "Single-high with pass alert",
                "pressure": "Standard rush",
                "aggression": "Balanced",
                "primary_focus": "Lean run first without losing pass integrity",
                "reason": (
                    f"Blended run lean is {blended_run_prob:.1%}, "
                    f"but live tendencies suggest the offense still may throw here."
                ),
                "situation_notes": situation_notes,
                "blended_pass_probability": round(blended_pass_prob, 3),
                "blended_run_probability": round(blended_run_prob, 3),
            }

        return {
            "defensive_personnel": "Base",
            "front": "Balanced-to-heavy front",
            "coverage_shell": "Single-high",
            "pressure": "Standard rush",
            "aggression": "Balanced",
            "primary_focus": "Lean run first",
            "reason": f"Blended run probability is {blended_run_prob:.1%}.",
            "situation_notes": situation_notes,
            "blended_pass_probability": round(blended_pass_prob, 3),
            "blended_run_probability": round(blended_run_prob, 3),
        }

    if long_yardage or down in [3, 4]:
        if softened:
            return {
                "defensive_personnel": "Nickel / Big Nickel",
                "front": "Balanced pass front",
                "coverage_shell": "Two-high with underneath awareness",
                "pressure": "Sim pressure optional",
                "aggression": "Balanced",
                "primary_focus": "Defend the sticks without giving away run support",
                "reason": (
                    f"Blended pass lean is {blended_pass_prob:.1%}, "
                    f"but live tendencies soften a full pass-commit recommendation."
                ),
                "situation_notes": situation_notes,
                "blended_pass_probability": round(blended_pass_prob, 3),
                "blended_run_probability": round(blended_run_prob, 3),
            }

        return {
            "defensive_personnel": "Nickel / Dime",
            "front": "Pass front",
            "coverage_shell": "Two-high / sticks shell",
            "pressure": "Sim pressure or pass-rush emphasis",
            "aggression": "Balanced",
            "primary_focus": "Defend the sticks / force checkdown",
            "reason": f"Blended pass probability is {blended_pass_prob:.1%} in a likely passing situation.",
            "situation_notes": situation_notes,
            "blended_pass_probability": round(blended_pass_prob, 3),
            "blended_run_probability": round(blended_run_prob, 3),
        }

    if red_zone:
        if softened:
            return {
                "defensive_personnel": "Big Nickel",
                "front": "Balanced front",
                "coverage_shell": "Match coverage",
                "pressure": "Selective pressure",
                "aggression": "Balanced",
                "primary_focus": "Protect quick-game while staying sound versus run",
                "reason": (
                    f"Blended pass lean is {blended_pass_prob:.1%}, "
                    f"but the live tendency does not support a full pass sellout."
                ),
                "situation_notes": situation_notes,
                "blended_pass_probability": round(blended_pass_prob, 3),
                "blended_run_probability": round(blended_run_prob, 3),
            }

        return {
            "defensive_personnel": "Nickel / Big Nickel",
            "front": "Balanced front",
            "coverage_shell": "Match coverage",
            "pressure": "Selective pressure",
            "aggression": "Balanced",
            "primary_focus": "Protect against quick-game and spacing concepts",
            "reason": f"Blended pass probability is {blended_pass_prob:.1%} in the red zone.",
            "situation_notes": situation_notes,
            "blended_pass_probability": round(blended_pass_prob, 3),
            "blended_run_probability": round(blended_run_prob, 3),
        }

    if medium_yardage:
        return {
            "defensive_personnel": "Nickel",
            "front": "Balanced pass front",
            "coverage_shell": "Two-high",
            "pressure": "Pressure optional",
            "aggression": "Moderate",
            "primary_focus": "Lean pass first while staying sound versus draw/RPO",
            "reason": f"Blended pass probability is {blended_pass_prob:.1%} in a medium-yardage situation.",
            "situation_notes": situation_notes,
            "blended_pass_probability": round(blended_pass_prob, 3),
            "blended_run_probability": round(blended_run_prob, 3),
        }

    return {
        "defensive_personnel": "Nickel",
        "front": "Balanced pass front",
        "coverage_shell": "Two-high",
        "pressure": "Pressure optional",
        "aggression": "Moderate",
        "primary_focus": "Lean pass first",
        "reason": f"Blended pass probability is {blended_pass_prob:.1%}.",
        "situation_notes": situation_notes,
        "blended_pass_probability": round(blended_pass_prob, 3),
        "blended_run_probability": round(blended_run_prob, 3),
    }


def classify_defensive_success(yards_gained: float, down: int, ydstogo: int) -> tuple[bool, str]:
    if down == 1:
        threshold = 0.4 * ydstogo
        rule = "1st down: offense needs at least 40% of yards-to-go"
    elif down == 2:
        threshold = 0.6 * ydstogo
        rule = "2nd down: offense needs at least 60% of yards-to-go"
    else:
        threshold = ydstogo
        rule = "3rd/4th down: offense needs full conversion"

    return yards_gained < threshold, rule


def classify_explosive_play(actual_play_type: str, yards_gained: float) -> bool:
    actual = actual_play_type.strip().upper()
    if actual == "RUN":
        return yards_gained >= 12
    return yards_gained >= 16


class GameTracker:
    STATE_SCHEMA_VERSION = 1

    def __init__(
        self,
        model_bundle: ModelBundle | None = None,
        state: dict | None = None,
    ):
        bundle = model_bundle or ModelBundle.load()
        self.model_bundle = bundle
        self.model = bundle.model
        self.model_columns = bundle.model_columns
        self.direction_model = bundle.direction_model
        self.direction_model_columns = bundle.direction_model_columns
        self.run_concept_model = bundle.run_concept_model
        self.run_concept_model_columns = bundle.run_concept_model_columns
        self.pass_concept_model = bundle.pass_concept_model
        self.pass_concept_model_columns = bundle.pass_concept_model_columns

        self.offense = None
        self.defense = None
        self.prev_play_pass = 0
        self.game_total_plays = 0
        self.game_total_passes = 0
        self.current_drive_number = 1
        self.drive_total_plays = 0
        self.drive_total_passes = 0
        self.situation_stats = self._empty_situation_stats()
        self.play_log = []
        self.pending_play_context = None

        if state:
            self.restore_state(state)

    @staticmethod
    def _empty_situation_stats() -> dict:
        return {
            "third_down": {"plays": 0, "passes": 0},
            "fourth_down": {"plays": 0, "passes": 0},
            "short_yardage": {"plays": 0, "passes": 0},
            "medium_yardage": {"plays": 0, "passes": 0},
            "long_yardage": {"plays": 0, "passes": 0},
            "red_zone": {"plays": 0, "passes": 0},
            "leading": {"plays": 0, "passes": 0},
            "trailing": {"plays": 0, "passes": 0},
        }

    def export_state(self) -> dict:
        """Return only JSON-serializable, game-specific mutable state."""
        return {
            "schema_version": self.STATE_SCHEMA_VERSION,
            "offense": self.offense,
            "defense": self.defense,
            "prev_play_pass": self.prev_play_pass,
            "game_total_plays": self.game_total_plays,
            "game_total_passes": self.game_total_passes,
            "current_drive_number": self.current_drive_number,
            "drive_total_plays": self.drive_total_plays,
            "drive_total_passes": self.drive_total_passes,
            "situation_stats": deepcopy(self.situation_stats),
            "play_log": deepcopy(self.play_log),
            "pending_play_context": deepcopy(self.pending_play_context),
        }

    def restore_state(self, state: dict) -> None:
        """Hydrate a request-local tracker from PostgreSQL or a legacy save."""
        self.offense = state.get("offense") or None
        self.defense = state.get("defense") or None
        self.play_log = deepcopy(state.get("play_log") or [])
        self.pending_play_context = deepcopy(
            state.get("pending_play_context", state.get("pending")) or None
        )

        self.current_drive_number = int(
            state.get("current_drive_number")
            or max(
                (int(play.get("drive_number", 1)) for play in self.play_log),
                default=1,
            )
        )

        counter_keys = {
            "prev_play_pass",
            "game_total_plays",
            "game_total_passes",
            "drive_total_plays",
            "drive_total_passes",
        }
        if counter_keys.issubset(state):
            self.prev_play_pass = int(state["prev_play_pass"])
            self.game_total_plays = int(state["game_total_plays"])
            self.game_total_passes = int(state["game_total_passes"])
            self.drive_total_plays = int(state["drive_total_plays"])
            self.drive_total_passes = int(state["drive_total_passes"])
        else:
            self._rebuild_counters_from_play_log()

        supplied_stats = state.get("situation_stats")
        if isinstance(supplied_stats, dict):
            empty_stats = self._empty_situation_stats()
            for key, default_value in empty_stats.items():
                raw_value = supplied_stats.get(key, default_value)
                empty_stats[key] = {
                    "plays": int(raw_value.get("plays", 0)),
                    "passes": int(raw_value.get("passes", 0)),
                }
            self.situation_stats = empty_stats
        else:
            self._rebuild_situation_stats_from_play_log()

    def _rebuild_counters_from_play_log(self) -> None:
        self.game_total_plays = len(self.play_log)
        self.game_total_passes = sum(
            1 for play in self.play_log if play.get("actual_play_type") == "PASS"
        )
        if self.play_log:
            self.prev_play_pass = int(
                self.play_log[-1].get("actual_play_type") == "PASS"
            )
        current_drive = [
            play
            for play in self.play_log
            if int(play.get("drive_number", 1)) == self.current_drive_number
        ]
        self.drive_total_plays = len(current_drive)
        self.drive_total_passes = sum(
            1 for play in current_drive if play.get("actual_play_type") == "PASS"
        )

    def _rebuild_situation_stats_from_play_log(self) -> None:
        self.situation_stats = self._empty_situation_stats()
        for play in self.play_log:
            actual = play.get("actual_play_type")
            if actual not in {"RUN", "PASS"}:
                continue
            self._update_situation_stats(
                down=int(play["down"]),
                ydstogo=int(play["ydstogo"]),
                yardline_100=int(play["yardline_100"]),
                score_differential=int(play["score_differential"]),
                is_pass=int(actual == "PASS"),
            )

    def tier2_available(self) -> bool:
        return self.model_bundle.tier2_available()

    def set_teams(self, offense, defense):
        self.offense = offense.strip().upper()
        self.defense = defense.strip().upper()

    def _current_game_pass_rate(self):
        if self.game_total_plays < 8:
            return 0.5
        return safe_rate(self.game_total_passes, self.game_total_plays)

    def _current_drive_pass_rate(self):
        if self.drive_total_plays < 4:
            return 0.5
        return safe_rate(self.drive_total_passes, self.drive_total_plays)

    def _is_short_yardage(self, down, ydstogo):
        return ydstogo <= 2

    def _is_medium_yardage(self, down, ydstogo):
        return (
            (down == 1 and 3 <= ydstogo <= 9)
            or (down == 2 and 3 <= ydstogo <= 7)
            or (down in [3, 4] and 3 <= ydstogo <= 6)
        )

    def _is_long_yardage(self, down, ydstogo):
        return (
            (down == 1 and ydstogo >= 11)
            or (down == 2 and ydstogo >= 8)
            or (down in [3, 4] and ydstogo >= 7)
        )

    def _is_red_zone(self, yardline_100):
        return yardline_100 <= 20

    def _context_keys(self, down, ydstogo, yardline_100, score_differential):
        keys = []

        if down == 3:
            keys.append("third_down")
        if down == 4:
            keys.append("fourth_down")

        if self._is_short_yardage(down, ydstogo):
            keys.append("short_yardage")
        elif self._is_medium_yardage(down, ydstogo):
            keys.append("medium_yardage")
        elif self._is_long_yardage(down, ydstogo):
            keys.append("long_yardage")

        if self._is_red_zone(yardline_100):
            keys.append("red_zone")

        if score_differential > 0:
            keys.append("leading")
        elif score_differential < 0:
            keys.append("trailing")

        return keys

    def _get_situation_snapshot(self, down, ydstogo, yardline_100, score_differential):
        keys = self._context_keys(down, ydstogo, yardline_100, score_differential)
        snapshot = {}

        for key in keys:
            plays = self.situation_stats[key]["plays"]
            passes = self.situation_stats[key]["passes"]
            snapshot[key] = {
                "plays": plays,
                "passes": passes,
                "pass_rate": round(safe_rate(passes, plays), 3),
            }

        return snapshot

    def _update_situation_stats(self, down, ydstogo, yardline_100, score_differential, is_pass):
        keys = self._context_keys(down, ydstogo, yardline_100, score_differential)
        for key in keys:
            self.situation_stats[key]["plays"] += 1
            self.situation_stats[key]["passes"] += is_pass

    def start_new_drive(self):
        self.current_drive_number += 1
        self.drive_total_plays = 0
        self.drive_total_passes = 0

    def _build_base_feature_df(
        self,
        down,
        ydstogo,
        yardline_100,
        game_seconds_remaining,
        qtr,
        score_differential,
    ):
        game_pass_rate = self._current_game_pass_rate()
        drive_pass_rate = self._current_drive_pass_rate()

        df = build_feature_row(
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            game_seconds_remaining=game_seconds_remaining,
            qtr=qtr,
            score_differential=score_differential,
            posteam=self.offense,
            defteam=self.defense,
            prev_play_pass=self.prev_play_pass,
            game_pass_rate=game_pass_rate,
            drive_pass_rate=drive_pass_rate,
        )

        df = pd.get_dummies(df, columns=["posteam", "defteam"], drop_first=True)
        return df, game_pass_rate, drive_pass_rate

    def _prepare_features_for_columns(
        self,
        model_columns,
        down,
        ydstogo,
        yardline_100,
        game_seconds_remaining,
        qtr,
        score_differential,
    ):
        df, game_pass_rate, drive_pass_rate = self._build_base_feature_df(
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            game_seconds_remaining=game_seconds_remaining,
            qtr=qtr,
            score_differential=score_differential,
        )
        df = df.reindex(columns=model_columns, fill_value=0)
        return df, game_pass_rate, drive_pass_rate

    def _predict_label_and_confidence(self, model, df):
        pred = model.predict(df)[0]

        confidence = None
        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(df)[0]
            confidence = float(max(probs))

        return pred, confidence

    def predict_next_play(
        self,
        down,
        ydstogo,
        yardline_100,
        game_seconds_remaining,
        qtr,
        score_differential,
    ):
        if self.offense is None or self.defense is None:
            raise ValueError("Teams not set. Call set_teams() first.")

        df, g_rate, d_rate = self._prepare_features_for_columns(
            self.model_columns,
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            game_seconds_remaining=game_seconds_remaining,
            qtr=qtr,
            score_differential=score_differential,
        )

        pred = self.model.predict(df)[0]
        prob = self.model.predict_proba(df)[0]

        prediction = "PASS" if pred == 1 else "RUN"
        run_prob = float(prob[0])
        pass_prob = float(prob[1])
        confidence = max(run_prob, pass_prob)
        tier = get_confidence_tier(run_prob, pass_prob)

        situation_alert = None
        if down == 4 and ydstogo >= 4 and prediction == "RUN":
            situation_alert = "PASS-DOWN ALERT: 4th & medium/long is usually pass-heavy"
        elif down == 3 and ydstogo >= 7 and prediction == "RUN":
            situation_alert = "PASS-DOWN ALERT: 3rd & long is usually pass-heavy"

        situational_snapshot = self._get_situation_snapshot(
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            score_differential=score_differential,
        )

        defensive_strategy = get_defensive_strategy(
            prediction=prediction,
            run_prob=run_prob,
            pass_prob=pass_prob,
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            score_differential=score_differential,
            confidence_tier=tier,
            situational_snapshot=situational_snapshot,
        )

        self.pending_play_context = {
            "drive_number": self.current_drive_number,
            "down": down,
            "ydstogo": ydstogo,
            "yardline_100": yardline_100,
            "game_seconds_remaining": game_seconds_remaining,
            "qtr": qtr,
            "score_differential": score_differential,
            "pred_prev_play_pass_used": self.prev_play_pass,
            "pred_game_pass_rate_used": g_rate,
            "pred_drive_pass_rate_used": d_rate,
            "situational_snapshot": situational_snapshot,
            "predicted_play_type": prediction,
            "run_probability": run_prob,
            "pass_probability": pass_prob,
            "confidence": confidence,
            "confidence_tier": tier,
            "situation_alert": situation_alert,
            "defensive_strategy": defensive_strategy,
        }

        return {
            "prediction": prediction,
            "run_probability": run_prob,
            "pass_probability": pass_prob,
            "confidence": round(confidence, 3),
            "confidence_tier": tier,
            "game_pass_rate_used": round(g_rate, 3),
            "drive_pass_rate_used": round(d_rate, 3),
            "situational_snapshot": situational_snapshot,
            "situation_alert": situation_alert,
            "defensive_strategy": defensive_strategy,
            "tier": 1,
        }

    def predict_next_play_tier2(
        self,
        down,
        ydstogo,
        yardline_100,
        game_seconds_remaining,
        qtr,
        score_differential,
    ):
        if not self.tier2_available():
            raise ValueError(
                "Tier 2 models are not available. Add direction_predictor_model.pkl, "
                "direction_model_columns.pkl, run_concept_predictor_model.pkl, "
                "run_concept_model_columns.pkl, pass_concept_predictor_model.pkl, "
                "and pass_concept_model_columns.pkl."
            )

        base_result = self.predict_next_play(
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            game_seconds_remaining=game_seconds_remaining,
            qtr=qtr,
            score_differential=score_differential,
        )

        direction_df, _, _ = self._prepare_features_for_columns(
            self.direction_model_columns,
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            game_seconds_remaining=game_seconds_remaining,
            qtr=qtr,
            score_differential=score_differential,
        )

        direction_pred, direction_conf = self._predict_label_and_confidence(
            self.direction_model,
            direction_df,
        )

        predicted_play_type = base_result["prediction"]

        if predicted_play_type == "RUN":
            concept_model = self.run_concept_model
            concept_columns = self.run_concept_model_columns
        else:
            concept_model = self.pass_concept_model
            concept_columns = self.pass_concept_model_columns

        concept_df, _, _ = self._prepare_features_for_columns(
            concept_columns,
            down=down,
            ydstogo=ydstogo,
            yardline_100=yardline_100,
            game_seconds_remaining=game_seconds_remaining,
            qtr=qtr,
            score_differential=score_differential,
        )

        concept_pred, concept_conf = self._predict_label_and_confidence(
            concept_model,
            concept_df,
        )

        tier2_result = {
            **base_result,
            "tier": 2,
            "play_direction_prediction": str(direction_pred),
            "play_direction_confidence": round(direction_conf, 3) if direction_conf is not None else None,
            "play_concept_prediction": str(concept_pred),
            "play_concept_confidence": round(concept_conf, 3) if concept_conf is not None else None,
        }

        if self.pending_play_context is not None:
            self.pending_play_context["play_direction_prediction"] = str(direction_pred)
            self.pending_play_context["play_direction_confidence"] = direction_conf
            self.pending_play_context["play_concept_prediction"] = str(concept_pred)
            self.pending_play_context["play_concept_confidence"] = concept_conf
            self.pending_play_context["tier"] = 2

        return tier2_result

    def log_pending_result(self, actual_play_type, yards_gained=None, epa=None):
        if self.pending_play_context is None:
            raise ValueError("No pending predicted play to log.")

        actual = actual_play_type.strip().upper()
        if actual not in ["RUN", "PASS"]:
            raise ValueError("actual_play_type must be 'run' or 'pass'")

        if yards_gained is None:
            raise ValueError("yards_gained is required for success tracking.")

        yards_gained = float(yards_gained)
        epa = None if epa is None else float(epa)
        is_pass = 1 if actual == "PASS" else 0

        play = self.pending_play_context.copy()
        play["actual_play_type"] = actual
        play["yards_gained"] = yards_gained
        play["epa"] = epa
        play["correct_prediction"] = play["predicted_play_type"] == actual

        defensive_success, success_rule = classify_defensive_success(
            yards_gained=yards_gained,
            down=play["down"],
            ydstogo=play["ydstogo"],
        )
        play["defensive_success"] = defensive_success
        play["success_rule"] = success_rule
        play["explosive_allowed"] = classify_explosive_play(actual, yards_gained)
        play["first_down_allowed"] = yards_gained >= play["ydstogo"]
        play["defensive_success_epa"] = None if epa is None else (epa < 0)

        self.play_log.append(play)

        self.prev_play_pass = is_pass
        self.game_total_plays += 1
        self.game_total_passes += is_pass
        self.drive_total_plays += 1
        self.drive_total_passes += is_pass

        self._update_situation_stats(
            down=play["down"],
            ydstogo=play["ydstogo"],
            yardline_100=play["yardline_100"],
            score_differential=play["score_differential"],
            is_pass=is_pass,
        )

        self.pending_play_context = None

    def summary(self) -> dict:
        plays = self.play_log
        if not plays:
            return {
                "total_predictions": 0,
                "correct_predictions": 0,
                "game_accuracy": None,
                "last_5_accuracy": None,
                "last_10_accuracy": None,
                "high_conf_accuracy": None,
                "pred_pass_accuracy": None,
                "pred_run_accuracy": None,
                "avg_conf_correct": None,
                "avg_conf_incorrect": None,
                "third_fourth_accuracy": None,
                "long_yardage_accuracy": None,
                "defensive_success_rate": None,
                "explosive_rate_allowed": None,
            }

        def accuracy(subset):
            if not subset:
                return None
            return sum(1 for play in subset if play["correct_prediction"]) / len(subset)

        def average_confidence(subset):
            if not subset:
                return None
            return sum(play["confidence"] for play in subset) / len(subset)

        total = len(plays)
        correct = sum(1 for play in plays if play["correct_prediction"])
        high_confidence = [play for play in plays if play["confidence"] >= 0.75]
        predicted_pass = [
            play for play in plays if play["predicted_play_type"] == "PASS"
        ]
        predicted_run = [
            play for play in plays if play["predicted_play_type"] == "RUN"
        ]
        correct_plays = [play for play in plays if play["correct_prediction"]]
        incorrect_plays = [play for play in plays if not play["correct_prediction"]]
        third_fourth = [play for play in plays if play["down"] in [3, 4]]
        long_yardage = [
            play
            for play in plays
            if (
                (play["down"] == 1 and play["ydstogo"] >= 11)
                or (play["down"] == 2 and play["ydstogo"] >= 8)
                or (play["down"] in [3, 4] and play["ydstogo"] >= 7)
            )
        ]
        defensive_successes = sum(
            1 for play in plays if play.get("defensive_success") is True
        )
        explosives = sum(
            1 for play in plays if play.get("explosive_allowed") is True
        )

        return {
            "total_predictions": total,
            "correct_predictions": correct,
            "game_accuracy": correct / total,
            "last_5_accuracy": accuracy(plays[-5:]),
            "last_10_accuracy": accuracy(plays[-10:]),
            "high_conf_accuracy": accuracy(high_confidence),
            "pred_pass_accuracy": accuracy(predicted_pass),
            "pred_run_accuracy": accuracy(predicted_run),
            "avg_conf_correct": average_confidence(correct_plays),
            "avg_conf_incorrect": average_confidence(incorrect_plays),
            "third_fourth_accuracy": accuracy(third_fourth),
            "long_yardage_accuracy": accuracy(long_yardage),
            "defensive_success_rate": defensive_successes / total,
            "explosive_rate_allowed": explosives / total,
        }
