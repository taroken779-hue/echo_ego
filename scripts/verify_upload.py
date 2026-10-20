"""生成済みの試験用WAVで音声登録を確認し、本人録音の確認とは区別する。"""
import json
import urllib.request
import urllib.error
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = "http://127.0.0.1:8100"
boundary = "echoego-test-boundary"
audio = (root / ".runtime" / "sample-1.wav").read_bytes()
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + audio + f'\r\n--{boundary}--\r\n'.encode())
request = urllib.request.Request(base + "/api/voices", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
with urllib.request.urlopen(request, timeout=30) as response:
    voice = json.load(response)
path = root / "voices" / (voice["name"] + ".wav")
try:
    with urllib.request.urlopen(base + "/api/status") as response:
        status = json.load(response)
    assert any(v["id"] == voice["id"] for v in status["voices"])
    assert path.is_file()
    for headers in [{"Origin": "https://example.com"}, {"Host": "example.com"}]:
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/api/status", headers=headers))
            raise AssertionError("Foreign origin/host accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 403
    print("WAV voice registration and foreign origin/host rejection passed.")
finally:
    # Only remove the unique fixture created by this test.
    path.unlink()
