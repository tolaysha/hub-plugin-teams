"""History is bound to expected account/channel/peer, never names or cache paths."""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['HUB_STATE_DIR'] = '/tmp/teams-ext-test'
import main
import sources


def captured():
    return {'chat_id': '123@c.us', 'messages': [{
        'id': 'abc', 'out': False, 'when': '9:35 AM, 10/12/2026', 'author': 'A', 'body': 'hello',
        'source': {'version': 1, 'channel': 'sample', 'account': '456', 'peer': '123@c.us',
                   'raw_id': 'false_123@c.us_abc', 'captured_at': '2026-10-15T10:00:00+00:00'}}]}


class HistoryIdentity(unittest.TestCase):
    ref = {'wa': 'sample', 'to': '123@c.us', 'account': '456', 'cmd': '/unused/wa'}

    def read(self, data, ref=None):
        with patch.object(sources, 'run', return_value=json.dumps(data)) as run:
            result = sources.history(self.ref if ref is None else ref)
        self.assertIn('--cached', run.call_args.args[0])
        return result

    def test_verified_rows_only(self):
        result = self.read(captured())[0]
        self.assertEqual(result['text'], 'hello')
        self.assertEqual(result['source'], captured()['messages'][0]['source'])

    def test_mismatched_envelope_or_row_rejects_entire_batch(self):
        variants = []
        d = captured(); d['chat_id'] = '999@c.us'; variants.append(d)
        for field, value in [('channel', 'other'), ('account', '999'), ('peer', '999@c.us'),
                             ('raw_id', 'false_999@c.us_abc'), ('raw_id', 'abc'),
                             ('captured_at', '2026-10-15T10:00:00')]:
            d = captured(); d['messages'][0]['source'][field] = value; variants.append(d)
        d = captured(); d['messages'][0].pop('source'); variants.append(d)
        d = captured(); d['messages'][0]['source'] = 'not an identity'; variants.append(d)
        d = captured(); d['messages'].append(copy.deepcopy(d['messages'][0])); variants.append(d)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(OSError):
                self.read(data)

    def test_missing_expected_account_does_not_trust_returned_account(self):
        ref = dict(self.ref); ref.pop('account')
        with self.assertRaises(OSError):
            self.read(captured(), ref)

    def test_identity_failure_invalidates_published_thread_without_read_or_send(self):
        class R:
            def close(self):
                pass
        st = {'refs': {'incoming': self.ref}}
        out = []
        with patch.object(sources, 'history', side_effect=OSError('Unverified WhatsApp history identity')):
            main.history(st, R(), {'history': 'incoming', 'ts': 1000}, out.append, now=1000)
        self.assertEqual(out, [{'kind': 'thread_failed', 'id': 'incoming', 'reset_history': True,
                               'error': 'Unverified WhatsApp history identity'}])


if __name__ == '__main__':
    unittest.main()
