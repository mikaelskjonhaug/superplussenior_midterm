"""Check the committed inputs and run the combined notebook in a fresh kernel."""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/sf_income_and_arrival_analysis.ipynb"


def input_content(path):
    """Make text checksums independent of Git line endings."""
    content = path.read_bytes()
    if path.suffix in {".csv", ".txt", ".json"}:
        content = content.replace(b"\r\n", b"\n")
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", choices=["root", "notebooks"], default="root")
    parser.add_argument(
        "--cleaned-only", action="store_true",
        help="Run in a temporary folder containing only the cleaned inputs.",
    )
    args = parser.parse_args()

    manifest = json.loads((ROOT / "data/notebook_inputs.json").read_text())
    for item in manifest["files"]:
        path = ROOT / item["path"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing committed notebook input: {path}")
        content = input_content(path)
        if len(content) != item["bytes"]:
            raise ValueError(f"Input size differs from the manifest: {path}")
        digest = hashlib.sha256(content).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"Input hash differs from the manifest: {path}")
    print(f"Verified {len(manifest['files'])} cleaned input files.", flush=True)

    workspace = None
    run_root = ROOT
    if args.cleaned_only:
        workspace = tempfile.TemporaryDirectory()
        run_root = Path(workspace.name)
        (run_root / "notebooks").mkdir()
        for item in manifest["files"]:
            destination = run_root / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / item["path"], destination)
    working_dir = run_root if args.cwd == "root" else run_root / "notebooks"
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    client = NotebookClient(
        notebook,
        kernel_name="python3",
        timeout=240,
        allow_errors=False,
        resources={"metadata": {"path": str(working_dir)}},
    )
    client.execute()

    for item in manifest["files"]:
        if item["path"].endswith(".csv"):
            table = pd.read_csv(run_root / item["path"])
            if len(table) != item["rows"]:
                raise ValueError(f"Unexpected row count: {item['path']}")

    figures = [
        "outputs/visualizations/sf_zip_acs_bracket_share_outliers.png",
        "outputs/visualizations/sf_zip_socioeconomic_status_street_network_map.png",
        "outputs/arrival_divergence/per_zip_flagged_cdfs.png",
        "outputs/arrival_divergence/most_significant_zip_ks_cdf.png",
        "outputs/arrival_divergence/per_zip_share_gaps.png",
        "outputs/income_access_service/stops_per_resident_vs_frequency.png",
        "outputs/income_access_service/on_time_by_income.png",
        "outputs/visualizations/transit_access_maps.png",
        "outputs/visualizations/trend_citywide.png",
        "outputs/visualizations/income_and_service.png",
    ]
    for filename in figures:
        path = run_root / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty figure: {filename}")

    if workspace is not None:
        shutil.copytree(run_root / "outputs", ROOT / "outputs", dirs_exist_ok=True)
        workspace.cleanup()
    nbformat.write(notebook, ROOT / "outputs/sf_income_and_arrival_analysis.executed.ipynb")
    scope = "cleaned inputs only" if args.cleaned_only else "repository checkout"
    print(f"Run All passed from {args.cwd}: {scope}, ten figures.")


if __name__ == "__main__":
    main()
