import tempfile
import unittest
from pathlib import Path
from lyrics import LocalLyrics, line_at, parse


class LyricsTests(unittest.TestCase):
    def test_lrc_formats_and_seek(self):
        rows = parse('[00:01.50]One\n[00:03:25]Two\n[00:05.000]\n[00:07]Three')
        self.assertIsNone(line_at(rows, 0))
        self.assertEqual(line_at(rows, 1.5), 'One')
        self.assertEqual(line_at(rows, 3.25), 'Two')
        self.assertIsNone(line_at(rows, 6))
        self.assertEqual(line_at(rows, 8), 'Three')
        self.assertEqual(line_at(rows, 2), 'One')

    def test_qrc_words_and_gap(self):
        rows = parse('<Lyric_1 LyricContent="[1000,500]你(1000,200)好(1200,300)&#10;[3000,1000]世界(3000,1000)"/>')
        self.assertEqual(line_at(rows, 1.1), '你好')
        self.assertIsNone(line_at(rows, 2))
        self.assertEqual(line_at(rows, 3.1), '世界')

    def test_offset(self):
        self.assertEqual(line_at(parse('[offset:500]\n[00:01]Earlier'), .5), 'Earlier')

    def test_multiple_timestamps(self):
        rows = parse('[00:01][00:10]Repeated')
        self.assertEqual([row.start for row in rows], [1, 10])

    def test_match_title_artist_duration_and_album(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Singer - Song - 180 - Album_qm.qrc'
            path.touch()
            provider = LocalLyrics(Path(folder))
            self.assertEqual(provider.find('Song', 'Singer', 'Album', 180), path)
            self.assertIsNone(provider.find('Other', 'Singer', 'Album', 180))
            self.assertIsNone(provider.find('Song', 'Stranger', 'Album', 180))
            self.assertIsNone(provider.find('Song', 'Singer', 'Album', 200))

    def test_ambiguous_versions_not_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            for album in ['One', 'Two']:
                (Path(folder) / f'Singer - Song - 180 - {album}_qm.qrc').touch()
            provider = LocalLyrics(Path(folder))
            self.assertIsNone(provider.find('Song', 'Singer', 'Unknown', 180))
            self.assertIsNotNone(provider.find('Song', 'Singer', 'One', 180))


if __name__ == '__main__':
    unittest.main()
