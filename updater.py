"""Opt-in installation from the project's official GitHub stable releases."""
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zipfile
from version import VERSION

REPOSITORY = 'pan0001/k1001-lyrics-bridge'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
INTERVAL = 24 * 60 * 60
MAX_DOWNLOAD = 300 * 1024 * 1024
MAX_EXPANDED = 900 * 1024 * 1024


def signal_ready():
    marker = os.environ.pop('SKYLYRICS_UPDATE_READY', '')
    if not marker or not getattr(sys, 'frozen', False):
        return
    path = Path(marker).resolve()
    if (path.name == 'ready' and re.fullmatch(r'\.sky-update-[a-f0-9]{32}', path.parent.name)
            and path.parent.parent == Path(sys.executable).resolve().parent.parent):
        path.write_text(VERSION, encoding='ascii')


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise ValueError('不支持的版本格式')
    return tuple(int(part) for part in value.lstrip('v').split('.'))


def select_release(data, current=VERSION):
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('不是正式发行版')
    tag = data.get('tag_name')
    if version_tuple(tag) <= version_tuple(current):
        return None
    name = f'SkyLyrics-v{tag.lstrip("v")}-windows-x64.zip'
    url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
    for asset in data.get('assets', []):
        if asset.get('name') != name:
            continue
        digest = asset.get('digest', '')
        size = asset.get('size')
        if asset.get('browser_download_url') != url or not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError('更新包缺少可信的 SHA-256 校验信息')
        if type(size) is not int or not 0 < size <= MAX_DOWNLOAD:
            raise ValueError('更新包大小异常')
        return dict(version=tag, url=url, size=size, sha256=digest[7:],
                    notes=str(data.get('body') or '此版本未填写更新说明。')[:12000])
    raise ValueError('新版尚未上传 Windows x64 安装包，请稍后重试')


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        'User-Agent': f'SkyLyrics/{VERSION}', 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'}), timeout=20)


def fetch_release():
    with request(API_URL) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('GitHub 响应过大')
    return json.loads(raw)


def download(release, destination, progress):
    digest, total, reported = hashlib.sha256(), 0, -1
    deadline = time.monotonic() + 600
    with request(release['url']) as response, destination.open('xb') as output:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('下载超时')
            chunk = response.read(128 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > release['size'] or total > MAX_DOWNLOAD:
                raise ValueError('更新包大小不符')
            digest.update(chunk)
            output.write(chunk)
            percent = total * 100 // release['size']
            if percent != reported:
                progress(f'正在下载更新… {percent}%')
                reported = percent
    if total != release['size'] or digest.hexdigest() != release['sha256']:
        raise ValueError('更新包校验失败，请重新下载')


def extract_application(archive, destination):
    prefix = 'SkyLyrics/app/SkyLyrics/'
    seen, size, count = set(), 0, 0
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            if not entry.filename.startswith(prefix):
                continue
            relative = entry.filename[len(prefix):]
            if not relative:
                continue
            parts = PurePosixPath(relative).parts
            if (not parts or '\\' in relative or relative.startswith('/') or
                    any(p in ('.', '..') or ':' in p or p.endswith((' ', '.')) or
                        p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(10)], *[f'LPT{i}' for i in range(10)]}
                        for p in parts) or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('更新包含非法文件路径')
            key = '/'.join(parts).lower()
            if key in seen:
                raise ValueError('更新包含重复文件')
            seen.add(key)
            size += entry.file_size
            count += 1
            if size > MAX_EXPANDED or count > 10000:
                raise ValueError('解压大小超出限制')
            target = destination.joinpath(*parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 128 * 1024)
    if not (destination/'SkyLyrics.exe').is_file() or not (destination/'_internal').is_dir():
        raise ValueError('更新包中缺少程序文件')


class Updater:
    def __init__(self, events, data_dir):
        self.events, self.data_dir = events, Path(data_dir)
        self.release = None
        self.busy = False
        self.lock = threading.Lock()
        self.cache = self.data_dir/'update-check.json'

    def emit(self, text, **values):
        self.events.put(('update_state', dict(text=text, **values)))

    def due(self):
        try:
            last = float(json.loads(self.cache.read_text(encoding='utf-8'))['attempt'])
            return not 0 <= time.time() - last < INTERVAL
        except (OSError, ValueError, KeyError, TypeError):
            return True

    def check(self, manual=False):
        with self.lock:
            if self.busy or (not manual and not self.due()):
                return
            self.busy = True
        def work():
            self.emit('正在连接 GitHub…', busy=True)
            try:
                self.cache.write_text(json.dumps({'attempt': time.time()}), encoding='utf-8')
                data = fetch_release()
                self.release = select_release(data)
                if self.release:
                    self.emit(f'发现新版 {self.release["version"]}', release=self.release, notify=not manual)
                else:
                    self.emit(f'GitHub 正式版 {data["tag_name"]}；当前 v{VERSION}，无需更新。', release=None)
            except Exception as exc:
                logging.info('Update check failed: %s', exc)
                self.emit('检查失败，请检查网络后重试。' if not isinstance(exc, ValueError) else str(exc))
            finally:
                with self.lock:
                    self.busy = False
                self.emit('', busy=False)
        threading.Thread(target=work, name='UpdateCheck', daemon=True).start()

    def install(self):
        with self.lock:
            if self.busy or not self.release:
                return
            if not getattr(sys, 'frozen', False):
                self.emit('源码运行时请从 GitHub 获取新版；自动安装仅用于打包版。')
                return
            self.busy = True
            release = dict(self.release)
        def work():
            folder = None
            handed_off = False
            try:
                target = Path(sys.executable).resolve().parent
                folder = target.parent/('.sky-update-' + uuid.uuid4().hex)
                folder.mkdir()
                self.emit('正在准备更新…', busy=True)
                archive = folder/'release.zip'
                download(release, archive, self.emit)
                self.emit('正在校验并解压…')
                extract_application(archive, folder/'new')
                archive.unlink()
                plan = dict(target=str(target), parent_pid=os.getpid(),
                            version=release['version'], status=str(self.data_dir/'update-result.json'))
                (folder/'plan.json').write_text(json.dumps(plan), encoding='utf-8')
                shutil.copyfile(Path(__file__).with_name('apply_update.ps1'), folder/'apply.ps1')
                subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                  '-File', str(folder/'apply.ps1')], cwd=folder,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                handed_off = True
                self.events.put(('update_install_ready', None))
            except Exception as exc:
                logging.exception('Update preparation failed')
                self.emit(f'更新未安装：{exc}。可重试或打开 GitHub 下载。')
            finally:
                if folder and not handed_off:
                    shutil.rmtree(folder, ignore_errors=True)
                with self.lock:
                    self.busy = False
                self.emit('', busy=False)
        threading.Thread(target=work, name='UpdateDownload', daemon=True).start()
