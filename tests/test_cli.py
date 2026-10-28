from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from early_risk_detection.bundle import ModelBundle
from early_risk_detection.cli import main


def test_help(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    assert "score" in capsys.readouterr().out


def test_bundle_info(tmp_path, capsys):
    b = ModelBundle.create(tmp_path / "b", "delay", {"features": ["a", "b"]})
    b.save_json("x.json", {})
    b.finalize({"test": {"roc_auc": 0.8}})
    main(["bundle", "info", str(tmp_path / "b")])
    info = json.loads(capsys.readouterr().out)
    assert info["kind"] == "delay" and info["files"] == ["x.json"] and info["config"]["features"] == "<2 entries>"


def test_eval_delay_passthrough(tmp_path):
    rng = np.random.default_rng(0)
    for s in ["val", "test"]:
        y = rng.integers(0, 2, 200)
        pd.DataFrame({"y_true": y, "y_prob": np.clip(y * 0.6 + rng.random(200) * 0.4, 0, 1)}).to_csv(
            tmp_path / f"{s}.csv", index=False)
    lb = tmp_path / "lb.json"
    main(["eval", "delay", "--predictions", str(tmp_path / "test.csv"), "--val-predictions", str(tmp_path / "val.csv"),
          "--track", "demo", "--leaderboard", str(lb)])
    assert json.loads(lb.read_text())["demo"]["test_metrics"]["roc_auc"] > 0.9
