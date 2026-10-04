"""Build an allowlisted source archive, excluding all private runtime data."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ["app.py", "run.py", "configuration.py", "store.py", "config.example.json", "requirements.txt", ".gitignore", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "start.bat", "stop.bat", "setup.bat", "scripts/start.ps1", "scripts/stop.ps1", "scripts/setup.ps1", "scripts/download_model.py", "scripts/package_release.py", "scripts/verify_features.py", "docs/USER_GUIDE.md", "docs/SETUP.md", "docs/DISTRIBUTION.md", "docs/IMPLEMENTATION.md", ".github/workflows/check.yml"]

def build():
    files = [ROOT / name for name in FILES]
    files += sorted((ROOT / "static").glob("*"))
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
