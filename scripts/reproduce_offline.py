"""Verify and recompute the reviewer package without model/network access."""
import sys
from khojki_ocr.delivery import main

if __name__ == "__main__":
    main(["reproduce", *sys.argv[1:]])
