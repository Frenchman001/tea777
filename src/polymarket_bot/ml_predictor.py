"""Machine learning models for market outcome prediction.

Uses lightweight scikit-learn-compatible approach with features extracted
from market data. No external ML dependencies required — uses pure Python
logistic regression fallback.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)

MODEL_PATH = Path.home() / ".polymarket_bot" / "ml_model.json"


@dataclass
class MarketFeatures:
    yes_price: float
    no_price: float
    spread: float
    volume_24h: float
    liquidity: float
    days_to_expiry: float
    price_momentum: float
    volume_ratio: float
    category_id: int

    def to_vector(self) -> list[float]:
        return [
            self.yes_price,
            self.no_price,
            self.spread,
            math.log1p(self.volume_24h),
            math.log1p(self.liquidity),
            math.log1p(max(self.days_to_expiry, 0)),
            self.price_momentum,
            self.volume_ratio,
            self.category_id,
        ]


@dataclass
class Prediction:
    market_slug: str
    question: str
    predicted_prob: float
    market_price: float
    edge: float
    confidence: float
    features: MarketFeatures
    recommended_side: str

    @property
    def has_value(self) -> bool:
        return abs(self.edge) > 0.05


CATEGORY_MAP = {
    "crypto": 1, "sports": 2, "politics": 3, "finance": 4,
    "tech": 5, "geopolitics": 6, "weather": 7, "economics": 8,
    "other": 0,
}


class SimpleLogisticModel:
    """Lightweight logistic regression without external dependencies.

    Stores learned weights and uses sigmoid for predictions.
    Can be replaced with sklearn.linear_model.LogisticRegression if available.
    """

    def __init__(self, n_features: int = 9) -> None:
        self.weights: list[float] = [0.0] * n_features
        self.bias: float = 0.0
        self.trained: bool = False
        self.n_features = n_features

    def _sigmoid(self, z: float) -> float:
        if z > 20:
            return 1.0
        if z < -20:
            return 0.0
        return 1.0 / (1.0 + math.exp(-z))

    def predict(self, features: list[float]) -> float:
        """Predict probability of YES outcome."""
        if not self.trained:
            return features[0] if features else 0.5

        z = self.bias
        for w, x in zip(self.weights, features):
            z += w * x
        return self._sigmoid(z)

    def train(
        self,
        X: list[list[float]],
        y: list[float],
        learning_rate: float = 0.01,
        epochs: int = 100,
    ) -> float:
        """Train on labeled data. Returns final loss."""
        if not X or not y:
            return 1.0

        n = len(X)
        for epoch in range(epochs):
            total_loss = 0.0
            for features, label in zip(X, y):
                pred = self.predict(features)
                error = pred - label
                total_loss += -(label * math.log(max(pred, 1e-10))
                                + (1 - label) * math.log(max(1 - pred, 1e-10)))

                for j in range(min(len(self.weights), len(features))):
                    self.weights[j] -= learning_rate * error * features[j]
                self.bias -= learning_rate * error

            avg_loss = total_loss / n
            if epoch % 20 == 0:
                logger.debug("Epoch %d: loss=%.4f", epoch, avg_loss)

        self.trained = True
        return avg_loss

    def save(self, path: Path | None = None) -> None:
        """Save model weights to disk."""
        save_path = path or MODEL_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "weights": self.weights,
            "bias": self.bias,
            "trained": self.trained,
            "n_features": self.n_features,
        }
        save_path.write_text(json.dumps(data))

    def load(self, path: Path | None = None) -> bool:
        """Load model weights from disk. Returns True if loaded."""
        load_path = path or MODEL_PATH
        if not load_path.exists():
            return False
        try:
            data = json.loads(load_path.read_text())
            self.weights = data["weights"]
            self.bias = data["bias"]
            self.trained = data["trained"]
            self.n_features = data["n_features"]
            return True
        except Exception as e:
            logger.warning("Failed to load model: %s", e)
            return False


class MLPredictor:
    """Market outcome predictor using machine learning."""

    def __init__(self) -> None:
        self.model = SimpleLogisticModel()
        self.model.load()

    def extract_features(
        self,
        market: Market,
        price_momentum: float = 0.0,
        volume_ratio: float = 1.0,
        category: str = "other",
    ) -> MarketFeatures:
        """Extract ML features from a market."""
        days = 30.0
        if market.end_date:
            from datetime import datetime, timezone
            try:
                end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days = max((end - now).total_seconds() / 86400, 0)
            except (ValueError, TypeError):
                pass

        return MarketFeatures(
            yes_price=market.yes_price,
            no_price=market.no_price,
            spread=market.spread,
            volume_24h=market.volume_24h,
            liquidity=market.liquidity,
            days_to_expiry=days,
            price_momentum=price_momentum,
            volume_ratio=volume_ratio,
            category_id=CATEGORY_MAP.get(category, 0),
        )

    def predict(
        self,
        market: Market,
        price_momentum: float = 0.0,
        volume_ratio: float = 1.0,
        category: str = "other",
    ) -> Prediction:
        """Predict the outcome probability for a market."""
        features = self.extract_features(market, price_momentum, volume_ratio, category)
        vector = features.to_vector()
        pred_prob = self.model.predict(vector)

        market_price = market.yes_price
        edge = pred_prob - market_price
        confidence = 1.0 - abs(pred_prob - 0.5) * 0.5

        side = "YES" if edge > 0 else "NO"

        return Prediction(
            market_slug=market.slug,
            question=market.question,
            predicted_prob=round(pred_prob, 4),
            market_price=market_price,
            edge=round(edge, 4),
            confidence=round(confidence, 4),
            features=features,
            recommended_side=side,
        )

    def predict_markets(
        self, markets: list[Market], min_edge: float = 0.05,
    ) -> list[Prediction]:
        """Predict outcomes for multiple markets, returning those with edge."""
        predictions: list[Prediction] = []
        for market in markets:
            pred = self.predict(market)
            if pred.has_value:
                predictions.append(pred)

        predictions.sort(key=lambda p: abs(p.edge), reverse=True)
        return predictions

    def train_on_resolved(
        self, resolved_markets: list[Market],
    ) -> float:
        """Train the model on resolved markets. Returns final loss."""
        X: list[list[float]] = []
        y: list[float] = []

        for market in resolved_markets:
            winner = ""
            for t in market.tokens:
                if t.winner:
                    winner = t.outcome.upper()
                    break

            if not winner:
                continue

            features = self.extract_features(market)
            X.append(features.to_vector())
            y.append(1.0 if winner == "YES" else 0.0)

        if len(X) < 10:
            logger.warning("Not enough resolved markets for training (%d)", len(X))
            return 1.0

        loss = self.model.train(X, y, epochs=200)
        self.model.save()
        logger.info("Model trained on %d markets, final loss: %.4f", len(X), loss)
        return loss
