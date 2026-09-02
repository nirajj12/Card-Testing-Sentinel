from __future__ import annotations

import pandas as pd

from card_testing_sentinel.ml.training_v3 import _training_weights


def test_v3_training_weights_preserve_device_mass_and_class_balance() -> None:
    frame = pd.DataFrame({
        "device_id": ["a", "a", "b", "c", "c", "c"],
        "label": [0, 0, 0, 1, 1, 1],
    })
    weights = _training_weights(frame)
    assert abs(weights.sum() - 3.0) < 1e-12
    assert abs(weights[frame.label.eq(0)].sum() - 1.5) < 1e-12
    assert abs(weights[frame.label.eq(1)].sum() - 1.5) < 1e-12
