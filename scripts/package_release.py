"""Build an allowlisted source archive, excluding all private runtime data."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ["app.py", "run.py", "configuration.py", "store.py", "config.example.json", "requirements.txt", ".gitignore", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "start.bat", "stop.bat", "setup.bat", "scripts/start.ps1", "scripts/stop.ps1", "scripts/setup.ps1", "scripts/migrate_config.py", "scripts/package_release.py", "scripts/verify_features.py", "docs/USER_GUIDE.md", "docs/DISCORD_GUIDE.md", "docs/SETUP.md", "docs/DISTRIBUTION.md", "docs/IMPLEMENTATION.md", ".github/workflows/check.yml"]

def build():
    files = [ROOT / name for name in FILES]
    files += [ROOT / name for name in ["reading_dictionary.py", "requirements-omnivoice.lock.txt", "setup_omnivoice.bat", "scripts/setup_omnivoice.ps1", "scripts/download_omnivoice.py", "scripts/verify_omnivoice.py", "docs/OMNIVOICE_GUIDE.md", "docs/OMNIVOICE_IMPLEMENTATION.md"]]
    files += sorted((ROOT / "speech").rglob("*.py"))
    files += sorted((ROOT / "static").glob("*"))
    files += [ROOT / "docs" / name for name in ["TTS_BACKEND_DESIGN.md", "TTS_BACKEND_GUIDE.md", "TTS_BACKEND_VALIDATION.md", "TTS_BACKEND_MIGRATION_TASKS.md", "LATENCY_IMPROVEMENTS_2026-10-22.md"]]
    files += [ROOT / "scripts" / name for name in ["verify_backend_api.py", "start_backend_validation.py"]]
    files += sorted((ROOT / "tests").glob("test_*.py"))
    dest = ROOT / "dist" / "echo-ego-source.zip"
    dest.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if not path.is_file():
                raise FileNotFoundError(path)
            content = path.read_bytes()
            # Prevent accidental introduction of this development PC's paths.
            if b"G:" + bytes([92]) + b"Irodori" in content or b"C:" + bytes([92]) + b"Users" + bytes([92]) + b"kamat" in content:
                raise ValueError(f"Private machine path in {path.name}")
            archive.writestr("echo-ego/" + path.relative_to(ROOT).as_posix(), content)
    print(dest)
    return dest

if __name__ == "__main__":
    build()
