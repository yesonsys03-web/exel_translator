from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from harmony_translate.cli import main as cli_main
from harmony_translate.ui import launch_ui


if __name__ == "__main__":
    if len(sys.argv) == 1:
        raise SystemExit(launch_ui())
    raise SystemExit(cli_main())
