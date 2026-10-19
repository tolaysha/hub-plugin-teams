"""Whole canonical manifest preserves private text independently of UI pages."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('HUB_STATE_DIR','/tmp/teams-management-test')
import main
import inbox_delivery as delivery


class WholeInbox(unittest.TestCase):
    def test_long_owner_guidance_is_exact_in_bounded_triage_chunks(self):
        import hashlib
        text=('"\n\t'+'x'*7)*200
        out=[]
        with patch.object(main,'triage_plugin',return_value='proactivity'):
            main.config({'cfg':{'prompt':text}},out.append)
        chunks=[p for p in out if p['kind']=='triage_prompt']
        self.assertTrue(all(len(json.dumps(p,ensure_ascii=False))<=1800 for p in chunks))
        self.assertEqual(''.join(p['text'] for p in chunks),text)
        self.assertEqual(chunks[0]['guidance_id'],hashlib.sha256(text.encode()).hexdigest())

    def test_recent_id_and_projection_caps_do_not_drop_open_work(self):
        from datetime import datetime,timezone
        st={'open':{f'k{n}':['thread','2026-10-15T12:00:00Z'] for n in range(3200)},
            'refs':{f'k{n}':{'chat':f'chat-{n}'} for n in range(3200)},
            'who':{f'k{n}':{'contact':f'chat-{n}'} for n in range(3200)}}
        main.tick(st,[],{},datetime(2026,10,15,tzinfo=timezone.utc),lambda _:None)
        self.assertEqual(len(st['open']),3200)
        self.assertEqual(len(st['refs']),3200)
        self.assertEqual(len(st['who']),3200)

    def test_unloaded_pages_and_exact_owner_guidance_are_in_canonical_manifest(self):
        st={'me':{'id':'account-a'},'cfg':{'prompt':'Use only verified source facts'},'open':{}}
        posts=[]
        for n in range(35):
            key=f'key-{n}'
            delivery.observe(st,{'key':key,'ref':{'chat':f'chat-{n}'},'text':'Current fact'})
            st['open'][key]=[f'chat-{n}','2026-10-15T12:00:00Z']
            posts.append({'id':f'p{100+n}','by':'плагин teams','text':json.dumps({'kind':'msg','id':key})})
        snapshot={'sessions':{'canonical':{'kind':'hub','state':'idle'}},'feeds':{main.NAME:posts}}
        exact='  Handle routine updates.\n Keep genuine decisions.  '
        out,told=[],[]
        with patch('core.journal.load_state',return_value=snapshot),patch.object(main,'save'), \
                patch.object(main,'deliver',side_effect=AssertionError('No transport')):
            main.manage_inbox(st,{'rid':'whole','text':exact},out.append,told.append)
            main.manage_inbox(st,{'rid':'whole','text':exact},out.append,told.append)
        self.assertEqual(len(told),5)
        self.assertEqual(st['inbox_management']['whole']['text'],exact)
        self.assertEqual(len(st['inbox_management']['whole']['items']),35)
        self.assertEqual(out[-1]['coverage']['count'],35)
        self.assertFalse(out[-1]['coverage']['upstream_exhaustive'])
        self.assertEqual(sum(p['kind']=='inbox_item' for p in out),35)
        self.assertTrue(all('Use only verified source facts' in t for t in told))
        self.assertIn('p134',told[-1])

    def test_missing_posts_and_source_failure_stay_visible_not_all_handled(self):
        st={'open':{'unloaded':['thread','date']},'src':{'email':{'fails':1}}}
        snapshot={'sessions':{'canonical':{'kind':'hub','state':'idle'}},'feeds':{}}
        out=[]
        with patch('core.journal.load_state',return_value=snapshot),patch.object(main,'save'):
            main.manage_inbox(st,{'rid':'partial','text':'Review all Inbox'},out.append,lambda _:None)
        self.assertEqual(out[-1]['coverage']['unavailable'],1)
        self.assertTrue(out[-1]['coverage']['source_warnings'])
        self.assertIn('unloaded',st['open'])
