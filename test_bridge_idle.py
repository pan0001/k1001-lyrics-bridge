import queue
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from bridge import Bridge


def session(app='QQMusic.exe', state=5):
    return NS(source_app_user_model_id=app,
              try_get_media_properties_async=AsyncMock(return_value=NS(title='Test song', artist='Artist', album_title='Album')),
              get_playback_info=lambda: NS(playback_status=state, playback_rate=None,
                                          controls=NS(is_next_enabled=True, is_previous_enabled=True, is_stop_enabled=True)),
              get_timeline_properties=lambda: NS(position=timedelta(seconds=40), start_time=timedelta(),
                                                end_time=timedelta(seconds=180), last_updated_time=datetime.now(timezone.utc)))


class BridgeIdleTests(unittest.IsolatedAsyncioTestCase):
    def make_bridge(self, sessions):
        bridge = Bridge(queue.Queue())
        bridge.mode = 'auto'
        bridge.selected = 'QQMusic.exe'
        bridge.manager = NS(get_sessions=lambda: sessions, get_current_session=lambda: sessions[0] if sessions else None)
        bridge.smtc = NS()
        bridge.lyrics.current = AsyncMock(return_value='Test lyric')
        bridge.sent = []
        bridge.publish = lambda title, *args, **kwargs: (bridge.sent.append(title) or timedelta(), timedelta())
        bridge.disable = lambda: None
        bridge.idle_clock.since = time.monotonic() - 301
        return bridge

    async def test_paused_enters_idle_then_play_restores_lyric(self):
        sessions = [session()]
        bridge = self.make_bridge(sessions)
        await bridge.poll()
        self.assertIn('CPU', bridge.sent[-1])
        self.assertIs(bridge.source, sessions[0])  # Device Play still controls the actual player.
        sessions[0] = session(state=4)
        await bridge.poll()
        self.assertEqual(bridge.sent[-1], 'Test lyric')
        self.assertIsNone(bridge.idle_clock.since)
        self.assertIsNone(bridge.idle_started)

    async def test_missing_player_enters_idle(self):
        bridge = self.make_bridge([])
        await bridge.poll()
        self.assertTrue(bridge.sent)

    async def test_other_player_playing_prevents_idle(self):
        bridge = self.make_bridge([session(), session('Other.exe', 4)])
        await bridge.poll()
        self.assertEqual(bridge.sent, ['Test lyric'])
        self.assertIsNone(bridge.idle_clock.since)

    async def test_stopped_never_publishes_idle(self):
        bridge = self.make_bridge([])
        bridge.mode = 'stopped'
        await bridge.poll()
        self.assertEqual(bridge.sent, [])

    async def test_preview_expires(self):
        bridge = self.make_bridge([session(state=4)])
        bridge.preview_until = time.monotonic() + 15
        await bridge.poll()
        self.assertIn('CPU', bridge.sent[-1])
        bridge.preview_until = 0
        await bridge.poll()
        self.assertEqual(bridge.sent[-1], 'Test lyric')


if __name__ == '__main__':
    unittest.main()
