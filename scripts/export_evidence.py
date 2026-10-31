"""Export code and private reviewer evidence as separate allowlisted zip files."""
import sys
from khojki_ocr.delivery import main

if __name__ == "__main__":
    main(["export", *sys.argv[1:]])
