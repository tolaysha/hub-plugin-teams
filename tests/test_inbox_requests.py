"""Authenticated private proposals, no Hub/model/transport runtime."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import inbox_delivery as delivery
import inbox_requests as requests


class PrivateResults(unittest.TestCase):
    def setUp(self):
        self.st={'me':{'id':'account-a'},'refs':{'a':{'chat':'chat-a'}}}
        item={'key':'a','text':'Current source','at':'2026-10-15T12:00:00Z','ref':{'chat':'chat-a'}}
        delivery.observe(self.st,item)
        self.posts=[{'id':'p123','by':'плагин teams','text':json.dumps({'kind':'msg','id':'a','reply':True})}]
        self.snapshot={'sessions':{'canonical':{'kind':'hub','state':'busy','launch_generation':7,'session_id':'hub-thread'}}}
        self.q={'id':'a','rid':'private-r','post':'p123','inbox':delivery.context(self.st,'a'),
                'instruction':'Use verified date only','draft':'','editor':'client-a'}
        self.request=requests.begin(self.st,self.q,self.snapshot,self.posts,'teams')
        self.result={'rid':'private-r','post':'p123','nonce':self.request['nonce'],'_author':'canonical',
                     'text':'Verified reply','context':'Verified context','next_action':'Check the date'}

    def test_result_requires_exact_author_generation_request_and_source(self):
        for change in ('author','generation','nonce','post','facts','edit','closed'):
            st,snapshot,posts,q=map(copy.deepcopy,(self.st,self.snapshot,self.posts,self.result))
            if change=='author': q['_author']='other'
            elif change=='generation': snapshot['sessions']['canonical']['launch_generation']=8
            elif change=='nonce': q['nonce']='other'
            elif change=='post': q['post']='p124'
            elif change=='facts': delivery.observe(st,{'key':'b','text':'New facts','ref':{'chat':'chat-a'}})
            elif change=='edit': delivery.control(st,{'id':'a','rid':'new-edit','inbox':delivery.context(st,'a'),'action':'hold','editor':'client-a'})
            else: posts.append({'id':'p124','by':'плагин teams','text':json.dumps({'kind':'answered','id':'a'})})
            with self.subTest(change=change), self.assertRaises(ValueError):
                requests.result(st,q,snapshot,posts,'teams')

    def test_restart_preserves_empty_edit_hold_and_one_explicit_apply_proposal(self):
        st=json.loads(json.dumps(self.st))
        self.assertEqual(st['inbox_requests']['private-r']['draft'],'')
        proposal=requests.result(st,self.result,self.snapshot,self.posts,'teams')
        self.assertEqual(proposal['kind'],'draft_proposal')
        self.assertTrue(proposal['requires_apply'])
        self.assertTrue(delivery.context(st,'a')['held'])
        self.assertNotIn('instruction',proposal)
        self.assertEqual(requests.result(st,self.result,self.snapshot,self.posts,'teams'),proposal)
        with self.assertRaises(ValueError):
            requests.result(st,{**self.result,'text':'Different candidate'},self.snapshot,self.posts,'teams')

    def test_deliberately_empty_private_draft_never_grants_send_authority(self):
        self.assertTrue(self.request['inbox']['held'])
        self.assertEqual(self.request['draft'],'')
        self.st['cfg']={'inbox_guard':True}
        with self.assertRaises(ValueError):
            delivery.claim(self.st,{'id':'a','rid':'auto','text':'hello','inbox':delivery.context(self.st,'a')})

    def test_actual_collector_revision_request_and_authenticated_result(self):
        import main
        # Start fresh: self.setUp already exercised the pure begin transition.
        st={'me':{'id':'account-a'},'refs':{'a':{'chat':'chat-a'}}}
        delivery.observe(st,{'key':'a','text':'Current source','at':'2026-10-15T12:00:00Z','ref':{'chat':'chat-a'}})
        snapshot={**self.snapshot,'feeds':{'teams':self.posts}}
        out,told=[],[]
        with patch('core.journal.load_state',return_value=snapshot),patch.object(main,'save'), \
                patch.object(main,'deliver',side_effect=AssertionError('No send')):
            main.ask_hub(st,self.q,out.append,told.append)
            request=st['inbox_requests'][self.q['rid']]
            result={**self.result,'nonce':request['nonce'],'revision_result':True}
            main.send_replies(st,None,[result],out.append)
        self.assertIn('Use verified date only',told[0])
        self.assertIn('"draft": ""',told[0])
        self.assertEqual([p['kind'] for p in out],['draft_state','asked','draft_proposal'])
        self.assertTrue(out[-1]['requires_apply'])
        self.assertTrue(delivery.context(st,'a')['held'])
