"""Start an isolated local validation server without changing ordinary app data."""
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from configuration import load_config


if __name__ == "__main__":
    folder=ROOT/".runtime/backend-validation"
    folder.mkdir(parents=True,exist_ok=True)
    config=load_config().model_copy(update={"port":8111,"preload":False,"presets_dir":"presets"})
    path=folder/"config.json"
    path.write_text(config.model_dump_json(indent=2),encoding="utf-8")
    os.environ["ECHO_EGO_CONFIG"]=str(path)
    os.environ["ECHO_EGO_DATA_DIR"]=str(folder/"data")
    # configuration was imported before choosing the isolated config.
    import configuration
    configuration.CONFIG_PATH=path
    os.chdir(ROOT)
    import uvicorn
    uvicorn.run("app:app",host="127.0.0.1",port=8111,access_log=False)
