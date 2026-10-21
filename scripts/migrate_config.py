"""Idempotent portable config migration, preserving custom paths and original data."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from configuration import CONFIG_PATH, RuntimeConfig, load_config, save_config
from store import Store
from configuration import data_dir


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")) if CONFIG_PATH.exists() else {}
    config = load_config()
    if args.cpu:
        config.models["omnivoice"].device = "cpu"
        config.models["omnivoice"].precision = "float32"
    if raw.get("python_path", ".venv/Scripts/python.exe") == ".venv/Scripts/python.exe":
        config.python_path = "runtime/app/.venv/Scripts/python.exe"
    if args.cpu or not raw or raw.get("schema_version") != 3 or raw.get("python_path") != config.python_path:
        save_config(config)
    Store(data_dir())
    print("Configuration and preferences migrated; original files are backed up before changes.")


if __name__ == "__main__":
    main()
