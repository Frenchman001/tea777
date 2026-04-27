"""Tests for ML predictor module."""

import tempfile
from pathlib import Path

from polymarket_bot.ml_predictor import (
    MarketFeatures,
    MLPredictor,
    Prediction,
    SimpleLogisticModel,
)
from polymarket_bot.models import Market, Token


def _make_market(slug: str, yes_price: float) -> Market:
    return Market(
        condition_id=f"c-{slug}", question=f"Will {slug} happen?", slug=slug,
        tokens=[
            Token(token_id=f"y-{slug}", outcome="Yes", price=yes_price),
            Token(token_id=f"n-{slug}", outcome="No", price=1 - yes_price),
        ],
        volume_24h=5000, liquidity=10000,
    )


def test_simple_model_untrained():
    model = SimpleLogisticModel()
    assert model.trained is False
    features = [0.5, 0.5, 0.0, 5.0, 7.0, 3.0, 0.0, 1.0, 0]
    pred = model.predict(features)
    assert pred == 0.5  # falls back to first feature


def test_simple_model_train_and_predict():
    model = SimpleLogisticModel(n_features=2)
    X = [[1.0, 0.0], [0.0, 1.0], [0.8, 0.2], [0.2, 0.8]]
    y = [1.0, 0.0, 1.0, 0.0]
    loss = model.train(X, y, epochs=100)
    assert loss < 1.0
    assert model.trained is True

    pred_high = model.predict([0.9, 0.1])
    pred_low = model.predict([0.1, 0.9])
    assert pred_high > pred_low


def test_model_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "model.json"
        model = SimpleLogisticModel(n_features=3)
        model.weights = [1.0, -1.0, 0.5]
        model.bias = 0.1
        model.trained = True
        model.save(path)

        model2 = SimpleLogisticModel(n_features=3)
        loaded = model2.load(path)
        assert loaded is True
        assert model2.weights == [1.0, -1.0, 0.5]
        assert model2.trained is True


def test_predictor_extract_features():
    predictor = MLPredictor()
    m = _make_market("btc", 0.6)
    features = predictor.extract_features(m, category="crypto")
    assert features.yes_price == 0.6
    assert features.category_id == 1


def test_predictor_predict():
    predictor = MLPredictor()
    m = _make_market("btc", 0.6)
    pred = predictor.predict(m)
    assert isinstance(pred, Prediction)
    assert 0 <= pred.predicted_prob <= 1


def test_predictor_predict_markets():
    predictor = MLPredictor()
    markets = [_make_market("m1", 0.2), _make_market("m2", 0.8)]
    preds = predictor.predict_markets(markets, min_edge=0.0)
    assert isinstance(preds, list)


def test_prediction_has_value():
    p = Prediction(
        market_slug="s", question="q", predicted_prob=0.7,
        market_price=0.5, edge=0.20, confidence=0.8,
        features=MarketFeatures(0.5, 0.5, 0, 1000, 5000, 30, 0, 1, 0),
        recommended_side="YES",
    )
    assert p.has_value is True

    p2 = Prediction(
        market_slug="s", question="q", predicted_prob=0.51,
        market_price=0.5, edge=0.01, confidence=0.5,
        features=MarketFeatures(0.5, 0.5, 0, 1000, 5000, 30, 0, 1, 0),
        recommended_side="YES",
    )
    assert p2.has_value is False
