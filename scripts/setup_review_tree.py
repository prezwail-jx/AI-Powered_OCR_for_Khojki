"""Extract explicitly provided delivery archives into a new private reviewer tree."""
import argparse
import shutil
import zipfile
from pathlib import Path

from khojki_ocr.delivery import inside, verify_index


def prepare(packages, destination, pdf=None):
    if destination.exists():
        raise ValueError("Reviewer destination already exists")
    destination.mkdir(parents=True)
    for package in ("code.zip", "review-evidence.zip"):
        with zipfile.ZipFile(packages / package) as archive:
            for member in archive.infolist():
                inside(destination, member.filename)
            archive.extractall(destination)
    verify_index(destination)
    verify_index(destination, "code-index.json")
    if pdf:
        shutil.copyfile(pdf, destination / "sample_khojki_script_vatiations.pdf")
    print(f"Private reviewer tree prepared: {destination}; no credentials copied")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    prepare(args.packages, args.destination, args.pdf)
