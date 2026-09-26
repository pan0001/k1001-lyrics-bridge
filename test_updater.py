import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

from updater import Updater, download, extract_application, select_release, version_tuple, REPOSITORY, INTERVAL, RETRY_INTERVAL
from idle_display import settings_from


def release(tag='v2.0.0'):
    name=f'SkyLyrics-{tag}-windows-x64.zip'
    return dict(tag_name=tag, assets=[dict(name=name,size=4,digest='sha256:'+hashlib.sha256(b'test').hexdigest(),
        browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}')])


class UpdateTests(unittest.TestCase):
    def finish_check(self, updater):
        deadline = time.monotonic() + 3
        while updater.busy and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(updater.busy)

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

    def test_failed_checks_retry_in_an_hour_and_successful_checks_wait_a_day(self):
        for success, interval in ((False, RETRY_INTERVAL), (True, INTERVAL)):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as folder:
                updater = Updater(queue.Queue(), folder)
                with patch('updater.time.time', return_value=1000000), patch(
                        'updater.fetch_release', return_value=release(),
                        side_effect=None if success else OSError('offline')):
                    updater.check()
                    self.finish_check(updater)
                # Retry timing survives restart as well as the current session.
                for instance in (updater, Updater(queue.Queue(), folder)):
                    with patch('updater.time.time', return_value=1000000 + interval - 1):
                        self.assertFalse(instance.due())
                    with patch('updater.time.time', return_value=1000000 + interval):
                        self.assertTrue(instance.due())

    def test_unwritable_cache_does_not_block_check_or_cause_retry_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            updater = Updater(queue.Queue(), folder)
            with patch.object(Path, 'write_text', side_effect=PermissionError('read only')), \
                    patch('updater.fetch_release', return_value=release()) as fetch:
                updater.check()
                self.finish_check(updater)
                self.assertEqual(updater.release['version'], 'v2.0.0')
                self.assertFalse(updater.due())
                updater.check()
                self.assertEqual(fetch.call_count, 1)


@unittest.skipUnless(os.name == 'nt', 'Windows updater transaction tests')
class UpdateTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():
            raise unittest.SkipTest('.NET Framework compiler unavailable')
        cls.fixture = tempfile.TemporaryDirectory(prefix='sky-update-test-')
        cls.root = Path(cls.fixture.name)
        source = cls.root / 'MockApp.cs'
        source.write_text('''using System; using System.IO; using System.Diagnostics; using System.Threading;
class App { static int Main() {
string dir=AppDomain.CurrentDomain.BaseDirectory;
if(File.Exists(Path.Combine(dir,"fail"))) return 9;
File.WriteAllText(Path.Combine(dir,"pid.txt"),Process.GetCurrentProcess().Id.ToString());
string marker=Environment.GetEnvironmentVariable("SKYLYRICS_UPDATE_READY");
if(!String.IsNullOrEmpty(marker)) File.WriteAllText(marker,"ready");
Thread.Sleep(60000); return 0; }}''', encoding='utf-8')
        cls.executable = cls.root / 'MockApp.exe'
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(cls.executable), str(source)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def transaction(self, *, fail=False, unwritable_status=False, extra_backups=False):
        import psutil
        case = self.root / uuid.uuid4().hex
        case.mkdir()
        target = case / '安装 SkyLyrics'
        target.mkdir()
        folder = case / ('.sky-update-' + uuid.uuid4().hex)
        new = folder / 'new'
        new.mkdir(parents=True)
        for app in (target, new):
            shutil.copy2(self.executable, app / 'SkyLyrics.exe')
        (target / 'old.txt').touch()
        (new / 'new.txt').touch()
        if fail:
            (new / 'fail').touch()
        status = case / 'result.json'
        if unwritable_status:
            status.mkdir()
        plan = dict(target=str(target), parent_pid=2147483647, version='test', status=str(status))
        (folder / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
        shutil.copyfile(Path(__file__).with_name('apply_update.ps1'), folder / 'apply.ps1')
        backups = {}
        if extra_backups:
            for name in ('completed', 'unfinished', 'other-app', 'linked'):
                backup = case / ('.sky-update-' + uuid.uuid4().hex)
                (backup / 'previous').mkdir(parents=True)
                (backup / 'previous' / 'keep.txt').touch()
                if name != 'unfinished':
                    receipt = dict(ok=True, target=str(case / 'other' if name == 'other-app' else target))
                    (backup / 'completed.json').write_text(json.dumps(receipt), encoding='utf-8')
                backups[name] = backup
            import _winapi
            outside = case / 'unrelated-data'
            outside.mkdir()
            (outside / 'keep.txt').touch()
            _winapi.CreateJunction(str(outside), str(backups['linked'] / 'previous' / 'link'))
        try:
            process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                      '-File', str(folder / 'apply.ps1')], capture_output=True, timeout=45,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(process.returncode, 1 if fail else 0, process.stderr.decode(errors='replace'))
            self.assertTrue((target / ('old.txt' if fail else 'new.txt')).is_file())
            if not unwritable_status:
                report = json.loads(status.read_text(encoding='utf-8-sig'))
                self.assertEqual(report['ok'], not fail)
            self.assertTrue((folder / ('failed' if fail else 'previous')).is_dir())
            if not fail:
                self.assertTrue((folder / 'completed.json').is_file())
            if extra_backups:
                self.assertFalse(backups['completed'].exists())
                self.assertTrue(backups['unfinished'].is_dir())
                self.assertTrue(backups['other-app'].is_dir())
                self.assertTrue(backups['linked'].is_dir())
                self.assertTrue((outside / 'keep.txt').is_file())
        finally:
            deadline = time.monotonic() + 3
            while not (target / 'pid.txt').exists() and time.monotonic() < deadline:
                time.sleep(.02)
            if (target / 'pid.txt').is_file():
                child = psutil.Process(int((target / 'pid.txt').read_text()))
                self.assertEqual(Path(child.exe()).resolve(), (target / 'SkyLyrics.exe').resolve())
                child.terminate()
                child.wait(5)

    def test_success_keeps_only_latest_completed_backup_for_this_app(self):
        self.transaction(extra_backups=True)

    def test_status_write_failure_does_not_rollback_healthy_app(self):
        self.transaction(unwritable_status=True)

    def test_failed_app_restores_previous_version(self):
        self.transaction(fail=True)


if __name__=='__main__':unittest.main()
