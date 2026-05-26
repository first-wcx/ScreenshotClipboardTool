from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

for path in (SRC,):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from integrated_tool.app import main  # noqa: E402


if __name__ == "__main__":
    main()
