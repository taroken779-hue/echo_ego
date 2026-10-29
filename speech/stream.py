"""Bounded binary frames shared by the worker and HTTP audio stream."""
import json
import struct

MAX_PCM = 192000


def pack(meta, pcm=b''):
    if len(pcm) > MAX_PCM:
        raise ValueError('音声チャンクが大きすぎます')
    header = json.dumps({**meta, 'bytes': len(pcm)}, ensure_ascii=False).encode()
    if len(header) > 8192:
        raise ValueError('音声ヘッダーが大きすぎます')
    return struct.pack('!I', len(header)) + header + pcm


def read_frame(stream):
    def exact(size):
        parts = bytearray()
        while len(parts) < size:
            chunk = stream.read(size-len(parts))
            if not chunk:
                raise ValueError('音声ストリームが途中で切断されました')
            parts.extend(chunk)
        return bytes(parts)
    size = struct.unpack('!I', exact(4))[0]
    if not 0 < size <= 8192:
        raise ValueError('音声ヘッダーが不正です')
    meta = json.loads(exact(size))
    count = meta.get('bytes')
    if type(count) is not int or not 0 <= count <= MAX_PCM:
        raise ValueError('音声チャンク長が不正です')
    return meta, exact(count)
