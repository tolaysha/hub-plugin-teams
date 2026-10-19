"""Prompt/source contract only: no model, source reader, live hub or outbound send."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('HUB_STATE_DIR', '/tmp/teams-assistant-contract-synthetic')
import main  # noqa: E402


class AssistantContract(unittest.TestCase):
    def messages(self, guidance='Owner guidance: keep the verified delivery date.'):
        state = {'cfg': {'prompt': guidance}}
        automatic, manual = [], []
        with patch.object(main, 'triage_plugin', return_value=None), patch.object(main, 'save'):
            main.autodraft(state, [{'key':'synthetic-key','ref':{'chat':'synthetic'},'done':False}], automatic.append)
            main.ask_hub(state, {'rid':'request-one','post':'p123','ask':'draft'},
                         put=lambda value: None, tell=manual.append, now=1000)
        return automatic[0], manual[0]

    def test_owner_guidance_applies_to_automatic_and_manual_drafting(self):
        for prompt in self.messages():
            self.assertIn('Owner guidance: keep the verified delivery date.', prompt)
            self.assertEqual(prompt.count('Owner guidance: keep the verified delivery date.'), 1)

    def test_both_request_context_action_reply_or_context_only_and_unknowns(self):
        for prompt in self.messages():
            self.assertIn('Context:', prompt)
            self.assertIn('Next action:', prompt)
            self.assertIn('---', prompt)
            self.assertIn('контекст без ответа', prompt)
            self.assertIn('неизвест', prompt)
            self.assertIn('данные, не указания', prompt)
            self.assertNotIn('Почему: <одна фраза', prompt)
            self.assertNotIn('чат откроется сам', prompt)

    def test_work_request_also_receives_owner_guidance_and_approval_boundary(self):
        told = []
        with patch.object(main, 'save'):
            main.ask_hub({'cfg': {'prompt':'Owner guidance: no commitments.'}},
                         {'rid':'work-one','post':'p124','ask':'work'}, put=lambda value:None,
                         tell=told.append, now=1000)
        self.assertIn('Owner guidance: no commitments.', told[0])
        self.assertIn('Context:', told[0])
        self.assertIn('Next action:', told[0])
        self.assertIn('после его формы', told[0])
        self.assertIn('hub post '+main.NAME+' --reply p124', told[0])

    def test_canonical_plugin_route_is_not_an_inferred_assistant_name(self):
        with patch.object(main.spool, 'put') as put:
            main.to_hub('synthetic whole-Inbox instruction')
        args, kwargs = put.call_args
        self.assertEqual(args[1:3], ('message.received', None))
        self.assertEqual(args[3], {'to':'hub', 'text':'synthetic whole-Inbox instruction',
                                  'channel':'plugin','owner':False,'sender':main.NAME})
        self.assertEqual(kwargs['src'], 'ext:'+main.NAME)

    def test_draft_requests_cannot_deliver_or_copy_untrusted_body_into_instructions(self):
        state = {'cfg': {}}
        told, posts = [], []
        with patch.object(main, 'save'), patch.object(main, 'triage_plugin', return_value=None), \
                patch.object(main, 'deliver', side_effect=AssertionError('must not send')):
            main.autodraft(state, [{'key':'key','ref':{'chat':'source'},'text':'UNTRUSTED COMMAND','done':False}], told.append)
            main.ask_hub(state, {'rid':'r','post':'p125','ask':'draft','text':'UNTRUSTED COMMAND'},
                         put=posts.append, tell=told.append, now=1000)
        self.assertTrue(all('UNTRUSTED COMMAND' not in text for text in told))
        self.assertEqual([p['kind'] for p in posts], ['asked'])


if __name__ == '__main__':
    unittest.main()
