import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from app.challenges import loader
from app.game.models import GamePhase, MatchState, PlayerState, RoomState, RoundEndReason
from app.realtime.match_setup import MatchSetupPolicy, available_categories, make_first_round, make_next_round


class FirstChoice:
    def choose_one(self, items):
        return items[0]


class CatalogTests(unittest.TestCase):
    def test_draft_bank_is_playable_only_when_explicitly_allowed(self):
        self.assertEqual(available_categories(MatchSetupPolicy(allow_draft_content=False)), ())
        self.assertEqual(available_categories(MatchSetupPolicy(allow_draft_content=True)),
                         ('object-oriented', 'back-end', 'c-plus-plus'))

    def test_next_round_uses_an_unused_challenge_with_fresh_document(self):
        now = datetime.now(timezone.utc)
        room = RoomState('TESTROOM', 'p1', (PlayerState('p1', 'Ada', now),), now,
            now + timedelta(hours=1), phase=GamePhase.ROLE_REVEAL,
            match=MatchState(match_id='match-1', selected_category_id='object-oriented'))
        first = make_first_round(room, now, MatchSetupPolicy())
        ended = replace(first, ended_at=first.deadline.due_at, end_reason=RoundEndReason.DEADLINE_EXPIRED)
        room = replace(room, phase=GamePhase.ROUND_RESULT,
                       match=replace(room.match, round_number=1, current_round=ended))
        second = make_next_round(room, ended.ended_at, MatchSetupPolicy(), choices=FirstChoice())
        self.assertEqual(first.challenge_id, 'oop.counter')
        self.assertEqual(second.challenge_id, 'oop.stack')
        self.assertNotEqual(first.current_source_revision_id, second.current_source_revision_id)

    def test_cache_invalidates_on_content_change_and_rejects_duplicate_versions(self):
        source = loader._CONTENT_DIRECTORY / 'oop.counter.v1.json'
        with TemporaryDirectory(dir=Path(__file__).parent) as directory, patch.object(loader, '_CONTENT_DIRECTORY', Path(directory)):
            target = Path(directory) / 'counter.json'
            target.write_bytes(source.read_bytes())
            first = loader.load_challenge('oop.counter', '1.0.0')
            self.assertIs(loader.load_challenge('oop.counter', '1.0.0'), first)
            payload = json.loads(target.read_text())
            payload['title'] = 'Changed challenge title for cache invalidation'
            target.write_text(json.dumps(payload))
            second = loader.load_challenge('oop.counter', '1.0.0')
            self.assertNotEqual(first.content_digest, second.content_digest)
            (Path(directory) / 'duplicate.json').write_text(json.dumps(payload))
            with self.assertRaises(loader.ChallengeLoadError):
                loader.load_challenge('oop.counter', '1.0.0')
