"""Model bundle: a directory holding every fitted artefact a scorer needs, plus ``manifest.json``.

Training scripts write bundles (``ModelBundle.create`` -> ``save_*`` -> ``finalize``); the
library only reads them (``ModelBundle.load``). The manifest records the bundle kind, the
library version that wrote it, free-form config / metrics, and a SHA-256 per file so a
corrupted or hand-edited bundle fails loudly.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

FORMAT_VERSION = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class BundleError(RuntimeError):
    pass


class ModelBundle:
    def __init__(self, path: Path, manifest: dict[str, Any]):
        self.path = path
        self.manifest = manifest

    # ---------------------------------------------------------------- create / load
    @classmethod
    def create(cls, path: str | Path, kind: str, config: dict[str, Any] | None = None,
               overwrite: bool = False) -> ModelBundle:
        from . import __version__

        p = Path(path)
        if p.exists():
            if not overwrite:
                raise BundleError(f"{p} already exists (pass overwrite=True)")
            shutil.rmtree(p)
        p.mkdir(parents=True)
        return cls(p, {"format_version": FORMAT_VERSION, "kind": kind, "library_version": __version__,
                       "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "config": config or {}, "metrics": {}, "files": {}})

    @classmethod
    def staging(cls, path: str | Path, kind: str) -> ModelBundle:
        """Open (or start) a bundle directory that several training steps fill before ``finalize``."""
        from . import __version__

        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        mf = p / "manifest.json"
        manifest = json.loads(mf.read_text()) if mf.exists() else {
            "format_version": FORMAT_VERSION, "kind": kind, "library_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "config": {}, "metrics": {}, "files": {}}
        if manifest["kind"] != kind:
            raise BundleError(f"{p} is a '{manifest['kind']}' bundle, expected '{kind}'")
        return cls(p, manifest)

    @classmethod
    def load(cls, path: str | Path, kind: str | None = None, verify: bool = True) -> ModelBundle:
        p = Path(path)
        mf = p / "manifest.json"
        if not mf.exists():
            raise BundleError(f"{p} is not a model bundle (missing manifest.json)")
        manifest = json.loads(mf.read_text())
        if manifest.get("format_version") != FORMAT_VERSION:
            raise BundleError(f"unsupported bundle format {manifest.get('format_version')} (expected {FORMAT_VERSION})")
        if kind is not None and manifest.get("kind") != kind:
            raise BundleError(f"{p} is a '{manifest.get('kind')}' bundle, expected '{kind}'")
        b = cls(p, manifest)
        if verify:
            for name, digest in manifest["files"].items():
                if not (p / name).exists():
                    raise BundleError(f"bundle file missing: {name}")
                if _sha256(p / name) != digest:
                    raise BundleError(f"bundle file corrupted or modified: {name}")
        return b

    def finalize(self, metrics: dict[str, Any] | None = None) -> Path:
        if metrics:
            self.manifest["metrics"].update(metrics)
        self.manifest["files"] = {f.relative_to(self.path).as_posix(): _sha256(f)
                                  for f in sorted(self.path.rglob("*")) if f.is_file() and f.name != "manifest.json"}
        (self.path / "manifest.json").write_text(json.dumps(self.manifest, indent=2, default=float))
        return self.path

    # ---------------------------------------------------------------- typed artefacts
    @property
    def kind(self) -> str:
        return self.manifest["kind"]

    @property
    def config(self) -> dict[str, Any]:
        return self.manifest["config"]

    def file(self, name: str) -> Path:
        return self.path / name

    def save_json(self, name: str, obj: Any) -> None:
        self.file(name).write_text(json.dumps(obj, indent=2, default=float))

    def load_json(self, name: str) -> Any:
        return json.loads(self.file(name).read_text())

    def save_arrays(self, name: str, **arrays: np.ndarray) -> None:
        np.savez(self.file(name), **arrays)

    def load_arrays(self, name: str) -> dict[str, np.ndarray]:
        with np.load(self.file(name), allow_pickle=False) as z:
            return {k: z[k] for k in z.files}

    def save_joblib(self, name: str, obj: Any) -> None:
        joblib.dump(obj, self.file(name))

    def load_joblib(self, name: str) -> Any:
        return joblib.load(self.file(name))

    def copy_in(self, src: str | Path, name: str | None = None) -> Path:
        dst = self.file(name or Path(src).name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst
