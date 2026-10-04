import logging
import os
import sys
from pathlib import Path
from configuration import load_config, resolve

root = Path(__file__).resolve().parent
os.chdir(root)
config = load_config()
sys.path.insert(0, str(resolve(config.source_path)))
os.environ["HF_HOME"] = str(resolve(config.hf_home))
# 初期導入後の発話はネットワークを使用しない。既存のcodecキャッシュを再利用。
os.environ["HF_HUB_OFFLINE"] = "1" if config.offline else "0"
os.environ["TRANSFORMERS_OFFLINE"] = "1" if config.offline else "0"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
import uvicorn
if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=config.port, access_log=False)
