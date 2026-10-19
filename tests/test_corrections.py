"""False unread closure repair, synthetic posts only; no real collector/sender."""
import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['HUB_STATE_DIR'] = '/tmp/teams-ext-test'
import main
import sources


class UnreadClosure(unittest.TestCase):
    def test_read_disappearance_and_restart_do_not_mean_answered(self):
        for source in ('whatsapp', 'telegram', 'email'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                Path(tmp, 'sources.json').write_text(json.dumps({source: {}}))
                box = 'wa:sample:123@c.us'
                st = {'src': {source: {'fails': 0, 'at': 0, 'boxes': [box]}},
                      'seen': ['incoming'], 'open': {'incoming': [box, '2026-10-15T10:00:00Z']}}
                st = json.loads(json.dumps(st))  # collector restarted; no in-memory unread workaround
                out = []
                with patch.object(main, 'OWN', tmp), patch.dict(sources.SOURCES,
                        {source: {'every': 0, 'fn': lambda *_: ([], set(), [])}}, clear=True):
                    got, cleared = main.run_sources(st, datetime.now(timezone.utc), out.append)
                    main.tick(st, got, {b: main.iso(datetime.now(timezone.utc)) for b in cleared},
                              datetime.now(timezone.utc), out.append)
                self.assertIn('incoming', st['open'])
                self.assertFalse(any(p.get('kind') == 'answered' for p in out))
                self.assertEqual(cleared, set())


def posts():
    def p(n, body, by='плагин teams', reply_to=None):
        return {'id': f'p{n}', 'by': by, 'text': json.dumps(body) if isinstance(body, dict) else body,
                'reply_to': reply_to}
    return [p(10, {'kind': 'msg', 'id': 'wa:sample:123@c.us:abc', 'contact': 'wa:sample:123@c.us',
                    'at': '2026-10-15T10:00:00Z', 'reply': True}),
            p(20, {'kind': 'answered', 'id': 'wa:sample:123@c.us:abc'}),
            p(21, {'kind': 'thread', 'id': 'wa:sample:123@c.us:abc', 'items': [{'text': 'wrong peer'}]}),
            p(22, 'unsent draft', 'helper', 'p10')]


class Correction(unittest.TestCase):
    def plan(self, feed=None, **kw):
        from corrections import plan_reopen
        return plan_reopen(posts() if feed is None else feed, 'p10', 'p20', **kw)

    def test_original_post_draft_and_history_are_preserved(self):
        feed = posts()
        before = copy.deepcopy(feed)
        event = self.plan(feed)
        self.assertEqual(feed, before)
        self.assertEqual(event, {'kind': 'reopened', 'id': 'wa:sample:123@c.us:abc',
                                'post': 'p10', 'corrects': 'p20', 'contact': 'wa:sample:123@c.us',
                                'reset_history': True})

    def test_stale_or_successfully_sent_closure_cannot_be_reopened(self):
        for kind in ('answered', 'sent'):
            feed = posts() + [{'id': 'p23', 'by': 'плагин teams',
                              'text': json.dumps({'kind': kind, 'id': 'wa:sample:123@c.us:abc', 'rid': 'r1'})}]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.plan(feed)

    def test_wrong_author_source_contact_and_superseded_item_rejected(self):
        for index, field, value in ((0, 'by', 'helper'), (1, 'by', 'owner')):
            feed = posts(); feed[index][field] = value
            with self.assertRaises(ValueError):
                self.plan(feed)
        feed = posts()
        data = json.loads(feed[1]['text']); data['id'] = 'other'
        feed[1]['text'] = json.dumps(data)
        with self.assertRaises(ValueError):
            self.plan(feed)
        feed = posts() + [{'id': 'p23', 'by': 'плагин teams', 'text': json.dumps({
            'kind': 'msg', 'id': 'wa:sample:123@c.us:new', 'contact': 'wa:sample:123@c.us'})}]
        with self.assertRaises(ValueError):
            self.plan(feed)

    def test_repeated_correction_is_idempotent_across_replay(self):
        feed = posts()
        feed.append({'id': 'p23', 'by': 'плагин teams', 'text': json.dumps(self.plan(feed))})
        self.assertIsNone(self.plan(json.loads(json.dumps(feed))))

    def test_plugin_queue_correction_restores_open_without_reading_or_sending(self):
        import corrections
        feed = posts()
        st = {'refs': {'wa:sample:123@c.us:abc': {'wa': 'sample', 'to': '123@c.us'}},
              'hist': {'wa:sample:123@c.us:abc||': 100}}
        out = []
        with patch.object(main, 'save'), patch.object(corrections, 'feed', return_value=feed):
            main.send_replies(st, None, [{'reopen': 'p10', 'corrects': 'p20'}], out.append)
        self.assertEqual(out, [self.plan()])
        self.assertEqual(st['open']['wa:sample:123@c.us:abc'],
                         ['wa:sample:123@c.us', '2026-10-15T10:00:00Z'])
        self.assertFalse(st['hist'])
        self.assertFalse(st.get('sent_rids'))

    def test_agent_cannot_impersonate_plugin_correction_request(self):
        body = {'kind': 'reopen', 'post': 'p10', 'corrects': 'p20'}
        for channel, sender, expected in [('session', 'helper', 0), ('plugin', 'other', 0),
                                           ('plugin', main.NAME, 1)]:
            c = main.Choice('/unused')
            c.line(json.dumps({'type': 'ext.post', 'seq': 50, 'data': {
                'plugin': main.NAME, 'channel': channel, 'sender': sender,
                'text': json.dumps(body)}}).encode())
            self.assertEqual(len(c.take_sends()), expected)

    def test_correction_trust_does_not_grant_self_send_permission(self):
        c = main.Choice('/unused')
        c.line(json.dumps({'type': 'ext.post', 'seq': 50, 'data': {
            'plugin': main.NAME, 'channel': 'plugin', 'sender': main.NAME,
            'text': json.dumps({'kind': 'send', 'id': 'incoming', 'rid': 'r', 'text': 'do not send'})}}).encode())
        self.assertFalse(c.take_sends())

    def test_stored_destination_mismatch_refuses_without_any_post_or_state_change(self):
        import corrections
        st = {'refs': {'wa:sample:123@c.us:abc': {'wa': 'sample', 'to': '999@c.us'}}}
        before = copy.deepcopy(st); out = []
        with patch.object(corrections, 'feed', return_value=posts()), self.assertRaises(ValueError):
            corrections.reopen(st, '/unused', 'teams', 'p10', 'p20', out.append)
        self.assertEqual(st, before)
        self.assertFalse(out)


if __name__ == '__main__':
    unittest.main()
