#!/usr/bin/env python3
"""Download the InsightFace buffalo_m model package."""

from __future__ import annotations

import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "buffalo_m"
URL = f"https://github.com/deepinsight/insightface/releases/download/v0.7/{MODEL_NAME}.zip"
TARGET_DIR = ROOT / "models" / MODEL_NAME
EXPECTED = {"1k3d68.onnx", "2d106det.onnx", "det_2.5g.onnx", "genderage.onnx", "w600k_r50.onnx"}


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        zip_path = tmp_dir / f"{MODEL_NAME}.zip"

        print(f"Downloading {URL}")
        urllib.request.urlretrieve(URL, zip_path)

        print("Extracting model package")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)

        extracted_root = tmp_dir / MODEL_NAME
        if not extracted_root.exists():
            extracted_root = tmp_dir

        for src in extracted_root.rglob("*.onnx"):
            shutil.copy2(src, TARGET_DIR / src.name)

    found = {p.name for p in TARGET_DIR.glob("*.onnx")}
    missing = sorted(EXPECTED - found)
    if missing:
        raise SystemExit(f"Missing model files: {', '.join(missing)}")

    total_mb = sum(p.stat().st_size for p in TARGET_DIR.glob("*.onnx")) / (1024 * 1024)
    print(f"Done: {TARGET_DIR}")
    print(f"Model size: {total_mb:.1f} MB")


if __name__ == "__main__":
    main()
