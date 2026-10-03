"""CLI entrypoint for daily ingestion. Implementation in src/ingest/run.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.run import run  # noqa: E402

if __name__ == "__main__":
    run()
