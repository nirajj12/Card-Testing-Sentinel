from pathlib import Path

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.features.spec import MODEL_FEATURES
from card_testing_sentinel.modeling.data import load_train_validation_views

ROOT = Path(__file__).resolve().parents[2]


def test_real_views_are_authorization_only_disjoint_and_leakage_free():
    settings = load_config(ROOT / "configs/base.yaml")
    train, validation = load_train_validation_views(settings)
    assert tuple(train.X.columns) == MODEL_FEATURES
    assert "entity_label" not in train.X
    assert set(train.metadata["device_id"]).isdisjoint(validation.metadata["device_id"])
    assert len(train.X) == 7372
    assert len(validation.X) == 1579
