from __future__ import annotations

import numpy as np
import pytest

from early_risk_detection.bundle import BundleError, ModelBundle


def test_round_trip_and_integrity(tmp_path):
    b = ModelBundle.create(tmp_path / "b", "demo", {"a": 1})
    b.save_arrays("arr.npz", x=np.arange(3))
    b.save_json("meta.json", {"k": [1, 2]})
    b.finalize({"test": {"auc": 0.9}})

    r = ModelBundle.load(tmp_path / "b", kind="demo")
    assert r.config == {"a": 1}
    assert r.manifest["metrics"]["test"]["auc"] == 0.9
    assert r.load_arrays("arr.npz")["x"].tolist() == [0, 1, 2]
    assert r.load_json("meta.json") == {"k": [1, 2]}

    with pytest.raises(BundleError, match="expected 'other'"):
        ModelBundle.load(tmp_path / "b", kind="other")
    (tmp_path / "b" / "meta.json").write_text("{}")
    with pytest.raises(BundleError, match="corrupted"):
        ModelBundle.load(tmp_path / "b")


def test_create_refuses_to_overwrite(tmp_path):
    ModelBundle.create(tmp_path / "b", "demo").finalize()
    with pytest.raises(BundleError, match="already exists"):
        ModelBundle.create(tmp_path / "b", "demo")
    ModelBundle.create(tmp_path / "b", "demo", overwrite=True)
