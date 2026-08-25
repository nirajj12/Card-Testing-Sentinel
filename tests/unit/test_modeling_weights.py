import numpy as np
import pandas as pd

from card_testing_sentinel.modeling.weights import evaluation_weights, training_weights


def test_evaluation_weights_give_each_device_equal_total_influence():
    devices = pd.Series(["busy", "busy", "busy", "patient"])
    weights = evaluation_weights(devices)
    totals = pd.Series(weights).groupby(devices).sum()
    assert np.allclose(totals.to_numpy(), [1.0, 1.0])


def test_training_weights_equalize_device_classes_and_device_influence():
    devices = pd.Series(["normal-a", "normal-a", "normal-b", "attack"])
    labels = pd.Series([0, 0, 0, 1])
    weights = training_weights(devices, labels)
    frame = pd.DataFrame({"device": devices, "label": labels, "weight": weights})
    assert np.allclose(frame.groupby("label")["weight"].sum().to_numpy(), [2.0, 2.0])
    normal_totals = frame[frame["label"].eq(0)].groupby("device")["weight"].sum()
    assert np.allclose(normal_totals.iloc[0], normal_totals.iloc[1])
    assert np.isfinite(weights).all() and (weights > 0).all()
