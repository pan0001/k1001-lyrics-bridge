import hashlib
import io
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from updater import Updater, download, extract_application, select_release, version_tuple, REPOSITORY
from idle_display import settings_from


def release(tag='v2.0.0'):
    name=f'SkyLyrics-{tag}-windows-x64.zip'
    return dict(tag_name=tag, assets=[dict(name=name,size=4,digest='sha256:'+hashlib.sha256(b'test').hexdigest(),
        browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}')])


class UpdateTests(unittest.TestCase):
    def test_version_order_and_no_downgrade(self):
        self.assertGreater(version_tuple('v1.10.0'),version_tuple('1.9.9'))
        self.assertIsNone(select_release(release('v1.1.1'), '1.1.4'))
        self.assertIsNone(select_release(release('v2.0.0'), '2.0.0'))
        for version in ('v1.0.0-rc1','../../2','1.0',None):
            with self.assertRaises(ValueError): version_tuple(version)

    def test_only_stable_official_assets_with_digest(self):
        self.assertEqual(select_release(release())['version'],'v2.0.0')
        for field,value in [('digest',None),('size',0),('browser_download_url','https://example.com/evil.zip')]:
            data=release();data['assets'][0][field]=value
            with self.assertRaises(ValueError): select_release(data)
        for field in ('draft','prerelease'):
            data=release();data[field]=True
            with self.assertRaises(ValueError): select_release(data)

    def test_download_checks_size_and_hash(self):
        for payload,valid in ((b'test',True),(b'bad!',False),(b'tes',False),(b'test!',False)):
            with tempfile.TemporaryDirectory() as folder, patch('updater.request',return_value=io.BytesIO(payload)):
                action=lambda:download(select_release(release()),Path(folder)/'update.zip',lambda text:None)
                if valid: action()
                else:
                    with self.assertRaises(ValueError): action()

    def archive(self,folder,extra=None):
        path=Path(folder)/'release.zip'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('SkyLyrics/app/SkyLyrics/SkyLyrics.exe',b'exe')
            z.writestr('SkyLyrics/app/SkyLyrics/_internal/library.dll',b'dll')
            z.writestr('SkyLyrics/source/not_installed.py',b'source')
            if extra:
                entry=zipfile.ZipInfo('placeholder')
                entry.filename='SkyLyrics/app/SkyLyrics/'+extra
                z.writestr(entry,b'bad')
        return path

    def test_extract_only_app(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'app'
            extract_application(self.archive(folder),target)
            self.assertEqual((target/'SkyLyrics.exe').read_bytes(),b'exe')
            self.assertFalse((target/'source').exists())

    def test_archive_rejects_traversal_streams_and_case_collisions(self):
        for extra in ('../../escape','/absolute','_internal/../escape','file:stream','CON.txt','trailing.',
                      'skylyrics.EXE'):
            with self.subTest(extra=extra),tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    extract_application(self.archive(folder,extra),Path(folder)/'app')

    def test_check_is_nonblocking_deduplicated_and_rate_limited(self):
        entered,finish=threading.Event(),threading.Event()
        def slow():
            entered.set();finish.wait(3);return release()
        with tempfile.TemporaryDirectory() as folder,patch('updater.fetch_release',side_effect=slow) as fetch:
            events=queue.Queue();updater=Updater(events,folder)
            try:
                started=time.monotonic();updater.check()
                self.assertLess(time.monotonic()-started,.2)
                self.assertTrue(entered.wait(1))
                updater.check(manual=True)
                self.assertEqual(fetch.call_count,1)
            finally:finish.set()
            for _ in range(30):
                if not updater.busy:break
                time.sleep(.05)
            self.assertFalse(updater.busy)
            self.assertFalse(updater.due())
            updater.check()
            self.assertEqual(fetch.call_count,1)

    def test_setting_defaults_and_opt_out_survive_save(self):
        self.assertTrue(settings_from({})['auto_update_check'])
        self.assertFalse(settings_from({'auto_update_check':False})['auto_update_check'])


if __name__=='__main__':unittest.main()
