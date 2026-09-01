import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.factory import create_app
from game_tracker import ModelBundle


class FakeBinaryModel:
    def predict(self, dataframe):
        return [1]

    def predict_proba(self, dataframe):
        return [[0.25, 0.75]]


@pytest.fixture
def model_bundle():
    return ModelBundle(model=FakeBinaryModel(), model_columns=[])


@pytest.fixture
def app(model_bundle):
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    return create_app(
        settings=settings,
        model_bundle=model_bundle,
        create_tables=True,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def create_game(client: TestClient, offense: str, defense: str) -> str:
    response = client.post(
        "/set-teams",
        json={"offense": offense, "defense": defense},
    )
    assert response.status_code == 201, response.text
    return response.json()["game_id"]


def prediction_payload(game_id: str) -> dict:
    return {
        "game_id": game_id,
        "down": 1,
        "ydstogo": 10,
        "yardline_100": 50,
        "game_seconds_remaining": 900,
        "qtr": 1,
        "score_differential": 0,
    }
