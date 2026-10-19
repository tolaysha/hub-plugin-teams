"""Producer acceptance of source-pinned synthetic native wire; no native runtime claim."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('HUB_STATE_DIR','/tmp/teams-native-wire-test')
import main
import inbox_delivery as delivery

FIXTURE=json.loads(Path(__file__).with_name('fixtures').joinpath('native-inbox-v1.json').read_text())


def packet(kind, token=None, **extra):
    body=copy.deepcopy(FIXTURE['requests'][kind])
    if token is not None:
        # The pinned InboxControl.json omits nil holder and unknown additive fields.
        body['inbox']={k:token[k] for k in FIXTURE['token_fields'] if token.get(k) is not None}
    body.update(extra)
    choice=main.Choice('/unused')
    event={'type':'ext.post','seq':10,'ts':1000,'data':{'plugin':main.NAME,'channel':'web','owner':True,
                                                    'text':json.dumps(body)}}
    choice.line(json.dumps(event).encode())
    (request,)=choice.take_sends()
    return body,request


class NativeWire(unittest.TestCase):
    def state(self):
        st={'me':{'id':'account-a'},'cfg':{'inbox_guard':False},
            'refs':{'source-a':{'chat':'chat-a','msg':'original'}},'open':{'source-a':['chat-a','2026-10-15T12:00:00Z']}}
        delivery.observe(st,{'key':'source-a','at':'2026-10-15T12:00:00Z','text':'Verified source',
                             'ref':st['refs']['source-a']})
        return st

    def test_native_manage_instruction_empty_draft_and_cancel_survive_real_choice_parser(self):
        body,q=packet('manage')
        self.assertTrue(q['manage'])
        self.assertEqual(q['text'],body['text'])
        token=delivery.context(self.state(),'source-a')
        body,q=packet('ask',token)
        for key in ('id','post','rid','editor','instruction','draft','inbox'):
            self.assertEqual(q[key],body[key])
        self.assertEqual(q['draft'],'')
        body,q=packet('cancel')
        self.assertEqual(q,{'cancel':body['rid'],'editor':body['editor'],'ts':1000})   # ts — свежесть повтора отмены (m461794)

    def test_producer_accepts_native_codec_when_fresh_server_token_is_supplied(self):
        st=self.state();out=[]
        _,hold=packet('hold',delivery.context(st,'source-a'))
        with patch.object(main,'save'),patch.object(main,'preflight_guarded'), \
                patch.object(main,'deliver',side_effect=[{'id':'own-1'},{'id':'own-2'}]) as send:
            main.send_replies(st,None,[hold],out.append)
            held=out[-1]['inbox']
            self.assertTrue(held['held'])
            _,first=packet('send',held)
            main.send_replies(st,None,[first],out.append)
            sent=next(d for d in out if d['kind']=='sent')
            self.assertTrue(sent['inbox']['manual_followup'])
            self.assertNotEqual(sent['inbox']['version'],first['inbox']['version'])
            body,follow=packet('send',sent['inbox'],rid='send-2',text='Additional reply')
            self.assertNotIn('manual_followup',body['inbox'])
            main.send_replies(st,None,[follow],out.append)
            self.assertEqual(send.call_count,2)
            sent=[d for d in out if d['kind']=='sent']
            self.assertEqual(len(sent),2)
            self.assertNotIn('source-a',st['open'])
            self.assertEqual(sent[-1]['submitted_inbox']['version'],follow['inbox']['version'])

    def test_native_codec_omission_cannot_turn_uncertainty_into_send_permission(self):
        st=self.state();out=[]
        _,request=packet('send',delivery.context(st,'source-a'))
        with patch.object(main,'save'),patch.object(main,'preflight_guarded'), \
                patch.object(main,'deliver',side_effect=TimeoutError('unknown')) as send:
            main.send_replies(st,None,[request],out.append)
            uncertain=out[-1]
            self.assertEqual(uncertain['kind'],'send_uncertain')
            self.assertFalse(uncertain['inbox']['manual_followup'])
            _,retry=packet('send',uncertain['inbox'],rid='different-request',text='New intent')
            main.send_replies(st,None,[retry],out.append)
            self.assertEqual(send.call_count,1)
            self.assertEqual(out[-1]['kind'],'send_blocked')
