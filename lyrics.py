"""Read QQ Music's existing local lyric cache; no network or account access.

Combined distribution: GPL-3.0-only. Decoder attribution in THIRD_PARTY.md.
"""
import asyncio
from bisect import bisect_right
from dataclasses import dataclass
import html
import logging
import os
from pathlib import Path
import re
import time
import unicodedata
import zlib
from qrc_des import DECRYPT, tripledes_key_setup, tripledes_crypt
from qrc_mask import qmc1_decrypt


@dataclass(frozen=True)
class Line:
    start: float
    end: float
    text: str


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


def decode_local(path):
    if path.stat().st_size > 2_000_000:
        raise ValueError('Lyric cache file exceeds size limit')
    data = bytearray(path.read_bytes())
    qmc1_decrypt(data)
    header_end = data.find(b'\n', 0, 64)
    header = bytes(data[:header_end]).strip()
    if header_end < 0 or not re.fullmatch(rb'\[offset:-?\d+\]', header):
        raise ValueError('Unsupported local QRC header')
    offset = int(header[8:-1]) / 1000
    data = data[header_end + 1:]
    if not data or len(data) % 8:
        raise ValueError('Incomplete QRC file')
    schedule = tripledes_key_setup(b'!@#)(*$%123ZXC!@!@#)(NHL', DECRYPT)
    compressed = b''.join(tripledes_crypt(data[i:i + 8], schedule) for i in range(0, len(data), 8))
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, 4_000_000)
    if not decoder.eof:
        raise ValueError('Incomplete or oversized lyric payload')
    return raw.decode('utf-8-sig'), offset


def parse(text, offset=0):
    # Attribute newlines must be preserved: XML parsers normalize them to spaces.
    # QQ cache can contain literal, unescaped quotes inside the attribute.
    # Only the quote immediately before the element terminator ends its payload.
    content = re.search(r'LyricContent\s*=\s*"(.*?)"\s*/>', text, re.S)
    if content:
        text = html.unescape(content.group(1))
    match = re.search(r'\[offset:([+-]?\d+)\]', text, re.I)
    if match:
        offset += int(match.group(1)) / 1000
    rows = []
    qrc = list(re.finditer(r'\[(\d+),(\d+)\]', text))
    if qrc:
        for i, m in enumerate(qrc):
            body = text[m.end():qrc[i + 1].start() if i + 1 < len(qrc) else len(text)]
            body = re.sub(r'\(\d+,\d+(?:,\d+)?\)', '', body).strip()
            start = int(m[1]) / 1000 - offset
            rows.append(Line(start, start + int(m[2]) / 1000, body))
    else:
        # QQ also caches LRC with [mm:ss:cc], as well as standard [mm:ss.cc].
        pattern = re.compile(r'\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]')
        for raw in text.splitlines():
            stamps = list(pattern.finditer(raw))
            if not stamps:
                continue
            body = raw[stamps[-1].end():].strip()
            for m in stamps:
                fraction = float('0.' + m[3]) if m[3] else 0
                rows.append(Line(int(m[1]) * 60 + int(m[2]) + fraction - offset, float('inf'), body))
        rows.sort(key=lambda row: row.start)
        rows = [Line(row.start, rows[i + 1].start if i + 1 < len(rows) else float('inf'), row.text)
                for i, row in enumerate(rows)]
    return sorted(rows, key=lambda row: row.start)


def line_at(rows, seconds):
    index = bisect_right([row.start for row in rows], seconds) - 1
    # Hold the last nonempty line through gaps and instrumental breaks.
    # Recompute from position so seeking backwards and song changes stay correct.
    while index >= 0:
        if rows[index].text:
            return rows[index].text
        index -= 1
    return None


class LocalLyrics:
    def __init__(self, folder=None):
        self.folder = folder or Path(os.environ['APPDATA']) / 'Tencent/QQMusic/QQMusicCache/QQMusicLyricNew'
        self.key = None
        self.rows = []
        self.pending = None
        self.retry_after = 0
        self.status = '等待歌词'
        self.cache = {}

    def find(self, title, artist, album, duration):
        target = normalize(title)
        artist_parts = [normalize(x) for x in re.split(r'[/&、;；]', artist) if normalize(x)]
        matches = []
        for path in self.folder.glob('*_qm.qrc'):
            # Original lyrics only: translations and romanization use other suffixes.
            m = re.fullmatch(r'(.+?) - (.+) - (\d+) - (.*)_qm\.qrc', path.name)
            if not m or normalize(m[2]) != target:
                continue
            if duration > 0 and abs(int(m[3]) - duration) > 3:
                continue
            cached_artist = normalize(m[1])
            if artist_parts and not any(part == cached_artist or part in cached_artist or cached_artist in part
                                        for part in artist_parts):
                continue
            score = (normalize(m[4]) == normalize(album), -abs(int(m[3]) - duration))
            matches.append((score, path))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        if len(matches) > 1 and matches[0][0] == matches[1][0]:
            # Ambiguous versions should fall back to the title, not guess lyrics.
            return None
        return matches[0][1]

    def load(self, key):
        path = self.find(*key)
        if path is None:
            return []
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
        if cache_key not in self.cache:
            text, offset = decode_local(path)
            self.cache[cache_key] = parse(text, offset)
            if len(self.cache) > 24:
                self.cache.pop(next(iter(self.cache)))
        return self.cache[cache_key]

    async def current(self, title, artist, album, duration, position):
        key = (title, artist, album, round(duration))
        if key != self.key:
            self.key = key
            self.rows = []
            self.retry_after = 0
            self.status = '正在读取 QQ 音乐歌词'
            # Keep at most one decoder running; discard its result after a song change.
        if self.pending and self.pending.done():
            pending_key, task = self.pending_key, self.pending
            self.pending = None
            try:
                result = task.result()
                if pending_key == self.key:
                    self.rows = result
                    self.status = '歌词同步' if result else '暂无本地歌词，显示歌名'
                    self.retry_after = time.monotonic() + 5
            except Exception as exc:
                logging.warning('Local lyrics unavailable: %s', type(exc).__name__)
                if pending_key == self.key:
                    self.status = '歌词暂不可读，显示歌名'
                    self.retry_after = time.monotonic() + 10
        if not self.rows and self.pending is None and time.monotonic() >= self.retry_after:
            self.pending_key = key
            self.pending = asyncio.create_task(asyncio.to_thread(self.load, key))
        return line_at(self.rows, position)

    async def close(self):
        if self.pending:
            try:
                await self.pending
            except Exception:
                pass
