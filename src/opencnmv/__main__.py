"""``python -m opencnmv`` -> the read-only CLI entry point."""
from opencnmv.cli.main import entry

if __name__ == "__main__":
    raise SystemExit(entry())
