"""Canonical collector delivery races: only synthetic accounts and transport."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('HUB_STATE_DIR', '/tmp/teams-inbox-delivery-test')
import main
import inbox_delivery as delivery


def incoming(key='a', text='Verified facts', chat='chat-a'):
    return {'key':key, 'text':text, 'at':'2026-10-15T12:00:00Z', 'src':'dm',
            'box':chat, 'ref':{'chat':chat}, 'from':'Person', 'contact':chat}


def state():
    st = {'me':{'id':'account-a'}, 'cfg':{'inbox_guard':True},
          'hours':{'from':'00:00','to':'24:00','weekends':True}}
    delivery.observe(st, incoming())
    st['refs'] = {'a':{'chat':'chat-a'}}
    st['open'] = {'a':['chat-a','2026-10-15T12:00:00Z']}
    return st


class Delivery(unittest.TestCase):
    def test_second_collector_writer_cannot_enter_shared_state(self):
        with tempfile.TemporaryDirectory() as folder:
            with delivery.writer_lock(str(Path(folder,'collector.lock'))):
                with self.assertRaises(OSError):
                    with delivery.writer_lock(str(Path(folder,'collector.lock'))):
                        self.fail('Second collector entered')
            with delivery.writer_lock(str(Path(folder,'collector.lock'))):
                pass

    def request(self, st, rid='manual', automatic=False):
        return {'id':'a', 'rid':rid, 'text':'Verified reply', 'inbox':delivery.context(st, 'a'),
                'automatic':automatic}

    def run_send(self, st, queue, result=None, error=None):
        out, calls, saved = [], [], []
        def send(*args, **kwargs):
            calls.append((args, kwargs))
            if error: raise error
            return result
        reader = type('Reader', (), {'close':lambda self:None})()
        with patch.object(main, 'save', side_effect=lambda s:saved.append(copy.deepcopy(s))), \
                patch.object(main, 'deliver', side_effect=send),patch.object(main,'preflight_guarded'):
            main.send_replies(st, reader, queue, out.append)
        return out, calls, saved

    def test_manual_auto_race_and_restart_have_one_commit(self):
        for reverse in (False, True):
            st = state()
            queue = [self.request(st), self.request(st,'auto',True)]
            if reverse: queue.reverse()
            out, calls, saved = self.run_send(st, queue, {'id':'external-123'})
            self.assertEqual(len(calls),1)
            self.assertTrue(any(s.get('inbox_delivery',{}).get('claims') for s in saved))
            self.assertEqual(len([p for p in out if p['kind']=='sent']),1)
            st = json.loads(json.dumps(st))
            self.assertEqual(self.run_send(st, [queue[-1]], {'id':'different'})[1],[])

    def test_guarded_send_and_archive_archives_after_receipt_and_on_replay(self):
        st = state(); q = {**self.request(st), 'archive': True, 'target': main.target_of(st['refs']['a'])}
        out, calls, _ = self.run_send(st, [q], {'id': 'external-123'})
        kinds = [p['kind'] for p in out]
        self.assertEqual(len(calls), 1)
        self.assertLess(kinds.index('sent'), kinds.index('archived'))
        self.assertEqual(next(p for p in out if p['kind'] == 'archived')['target'], q['target'])
        self.assertEqual(next(p for p in out if p['kind'] == 'archived')['receipt']['id'], 'external-123')
        st = json.loads(json.dumps(st))
        out, calls, _ = self.run_send(st, [q], {'id': 'never'})
        self.assertEqual((calls, [p['kind'] for p in out]), ([], ['send_duplicate', 'archived']))
        import time   # перечитанный журнал после перезапуска — молча; свежий повтор клиента — итог (m486924)
        out, calls, _ = self.run_send(st, [{**q, 'ts': time.time() - 86400}], {'id': 'never'})
        self.assertEqual((calls, out), ([], []))
        out, calls, _ = self.run_send(st, [{**q, 'ts': time.time()}], {'id': 'never'})
        self.assertEqual((calls, [p['kind'] for p in out]), ([], ['send_duplicate', 'archived']))
        out, calls, _ = self.run_send(st, [{k: v for k, v in q.items() if k != 'archive'}], {'id': 'never'})
        self.assertEqual((calls, [p['kind'] for p in out]), ([], ['send_blocked']))
        for receiptless in ({'kind': 'sent', 'id': 'a', 'rid': 'x', 'receipt': None},
                            {'kind': 'send_duplicate', 'id': 'a', 'rid': 'x', 'state': 'sent'},
                            {'kind': 'send_duplicate', 'id': 'a', 'rid': 'x', 'state': 'sent', 'receipt': {'id': ''}}):
            got = []
            main.archive_after({'archive_rids': {'x': {'id': 'a'}}}, got.append)(receiptless)
            self.assertEqual([p['kind'] for p in got], [receiptless['kind']], receiptless)
        st = state(); q = {**self.request(st, 'uncertain'), 'archive': True}
        out, _, _ = self.run_send(st, [q], error=TimeoutError('unknown'))
        self.assertNotIn('archived', [p['kind'] for p in out])

    def test_hold_and_intentional_empty_survive_restart_release_is_explicit_cas(self):
        st = state(); old = delivery.context(st,'a')
        held = delivery.control(st, {'id':'a','rid':'edit','inbox':old,'action':'hold','editor':'client-a','draft':''})
        self.assertTrue(held['held'])
        st = json.loads(json.dumps(st))
        self.assertEqual(self.run_send(st,[self.request(st,'auto',True)],{'id':'x'})[1],[])
        with self.assertRaises(ValueError):
            delivery.control(st, {'id':'a','rid':'release','inbox':old,'action':'release','editor':'client-a'})
        current = delivery.context(st,'a')
        released = delivery.control(st, {'id':'a','rid':'release','inbox':current,'action':'release','editor':'client-a'})
        self.assertFalse(released['held'])

    def test_manual_send_atomically_consumes_own_hold_without_auto_activation(self):
        st=state(); st['cfg']['inbox_guard']=False
        held=delivery.control(st,{'id':'a','rid':'edit','inbox':delivery.context(st,'a'),
                                  'action':'hold','editor':'client-a'})
        for automatic,editor in ((True,'client-a'),(False,'client-b')):
            self.assertEqual(self.run_send(st,[{**self.request(st,'loser',automatic),'editor':editor}],{'id':'x'})[1],[])
        out,calls,saved=self.run_send(st,[{**self.request(st),'editor':'client-a'}],{'id':'external-id'})
        self.assertEqual(len(calls),1)
        self.assertEqual(out[0]['kind'],'sent')
        claimed=next(s for s in saved if s['inbox_delivery']['claims'])
        self.assertFalse(delivery.context(claimed,'a')['held'])
        self.assertTrue(claimed['inbox_delivery']['claims'])

    def test_other_client_cannot_steal_or_release_hold_and_replay_does_not_increment(self):
        st=state(); q={'id':'a','rid':'edit','inbox':delivery.context(st,'a'),'action':'hold','editor':'client-a'}
        held=delivery.control(st,q)
        self.assertEqual(delivery.control(st,q),held)
        for action in ('hold','release'):
            with self.assertRaises(ValueError):
                delivery.control(st,{**q,'rid':action,'inbox':held,'action':action,'editor':'client-b'})
        fresh=delivery.control(st,{**q,'rid':'new-edit','inbox':held})
        self.assertEqual(fresh['edit_version'],held['edit_version']+1)

    def new_source(self, st, key='b', chat='chat-a'):
        item=incoming(key,'New verified facts',chat)
        st.setdefault('refs',{})[key]=item['ref']
        st.setdefault('open',{})[key]=[chat,item['at']]
        delivery.observe(st,item)

    def edit(self, st, key='a', editor='client-a', rid='hold'):
        return delivery.control(st,{'id':key,'rid':rid,'inbox':delivery.context(st,key),
                                    'action':'hold','editor':editor})

    def test_conversation_hold_blocks_new_key_before_client_poll_and_after_restart(self):
        st=state(); self.edit(st)
        self.new_source(st)
        st=json.loads(json.dumps(st))
        token=delivery.context(st,'b')
        self.assertTrue(token['held'])
        self.assertEqual(token['holder'],'client-a')
        q={**self.request(st,'auto-new',True),'id':'b','inbox':token}
        out,calls,_=self.run_send(st,[q],{'id':'must-not-submit'})
        self.assertEqual(calls,[])
        self.assertFalse(any(p['kind']=='sent' for p in out))

    def test_hold_covers_already_observed_sibling_and_other_client_cannot_release(self):
        st=state(); self.new_source(st)
        before=delivery.context(st,'b')
        self.edit(st)
        token=delivery.context(st,'b')
        self.assertTrue(token['held'])
        self.assertGreater(token['edit_version'],before['edit_version'])
        for action in ('hold','release'):
            with self.assertRaises(ValueError):
                delivery.control(st,{'id':'b','rid':action,'inbox':token,
                                     'action':action,'editor':'client-b'})

    def test_new_key_manual_send_consumes_conversation_hold_with_claim_atomically(self):
        st=state(); st['cfg']['inbox_guard']=False
        self.edit(st); old=self.request(st)
        self.new_source(st)
        old['editor']='client-a'
        self.assertFalse(self.run_send(st,[old],{'id':'must-not-submit'})[1])
        token=delivery.context(st,'b')
        q={**self.request(st,'new-manual'),'id':'b','inbox':token,'editor':'client-a'}
        out,calls,saved=self.run_send(st,[q],{'id':'new-receipt'})
        self.assertTrue(token['held'])
        self.assertEqual(len(calls),1)
        self.assertEqual(out[0]['kind'],'sent')
        claimed=next(s for s in saved if s['inbox_delivery']['claims'])
        self.assertFalse(delivery.context(claimed,'a')['held'])
        self.assertFalse(delivery.context(claimed,'b')['held'])
        self.assertEqual(len(claimed['inbox_delivery']['claims']),1)

    def test_only_explicit_current_token_release_clears_conversation_hold(self):
        st=state(); old=self.edit(st)
        self.new_source(st)
        with self.assertRaises(ValueError):
            delivery.control(st,{'id':'a','rid':'stale','inbox':old,'action':'release','editor':'client-a'})
        token=delivery.context(st,'b')
        self.assertTrue(token['held'])
        delivery.control(st,{'id':'b','rid':'release','inbox':token,'action':'release','editor':'client-a'})
        self.assertFalse(delivery.context(st,'a')['held'])
        self.assertFalse(delivery.context(st,'b')['held'])

    def test_hold_identity_is_account_and_conversation_not_source_key(self):
        st=state(); self.edit(st)
        self.new_source(st,'other-chat','chat-b')
        self.assertFalse(delivery.context(st,'other-chat')['held'])
        st['me']['id']='account-b'
        self.new_source(st,'other-account')
        self.assertFalse(delivery.context(st,'other-account')['held'])
        st['me']['id']='account-a'
        self.new_source(st,'back-to-account-a')
        self.assertTrue(delivery.context(st,'back-to-account-a')['held'])

    def test_legacy_conflicting_row_holds_migrate_without_releasing_either_editor(self):
        st=state(); self.new_source(st)
        db=st['inbox_delivery']; del db['editors']
        for key,editor,version in (('a','client-a',1),('b','client-b',2)):
            db['items'][key].update(held=True,holder=editor,edit_version=version)
        self.new_source(st,'c')
        st=json.loads(json.dumps(st))
        ctx=delivery.context(st,'c')
        self.assertTrue(ctx['held'])
        self.assertIsNone(ctx['holder'])
        self.assertEqual(ctx['edit_version'],2)
        q={**self.request(st,'blocked-migration',True),'id':'c','inbox':ctx}
        self.assertFalse(self.run_send(st,[q],{'id':'must-not-submit'})[1])
        with self.assertRaises(ValueError): self.edit(st,'c','client-c','steal')
        delivery.control(st,{'id':'c','rid':'release-a','inbox':ctx,'action':'release','editor':'client-a'})
        ctx=delivery.context(st,'c')
        self.assertEqual(ctx['holder'],'client-b')
        self.assertTrue(ctx['held'])
        delivery.control(st,{'id':'c','rid':'release-b','inbox':ctx,'action':'release','editor':'client-b'})
        self.assertFalse(delivery.context(st,'a')['held'])
        self.assertFalse(delivery.context(st,'c')['held'])

    def test_new_conversation_hold_during_preflight_blocks_final_claim(self):
        st=state(); self.new_source(st)
        q={**self.request(st,'auto-race',True),'id':'b','inbox':delivery.context(st,'b')}
        with patch.object(main,'save'),patch.object(main,'deliver') as send, \
                patch.object(main,'preflight_guarded',side_effect=lambda *_:self.edit(st)):
            main.send_replies(st,None,[q],lambda _:None)
            send.assert_not_called()
        self.assertTrue(delivery.context(st,'b')['held'])
        self.assertFalse(st['inbox_delivery']['claims'])

    def test_cancel_scheduled_old_source_holds_new_conversation_source(self):
        from datetime import datetime,timezone
        st=state(); q={**self.request(st),'at':'2030-01-01T08:00:00Z','editor':'client-a'}
        with patch.object(main,'save'),patch.object(main,'deliver') as send:
            main.send_replies(st,None,[q],lambda _:None,datetime(2026,1,1,tzinfo=timezone.utc))
            self.new_source(st)
            main.send_replies(st,None,[{'cancel':q['rid'],'editor':'client-a'}],lambda _:None)
            send.assert_not_called()
        self.assertTrue(delivery.context(st,'b')['held'])
        self.assertEqual(delivery.context(st,'b')['holder'],'client-a')

    def test_confirmed_send_issues_fresh_manual_followup_token_without_reopening_auto_work(self):
        st=state(); st['cfg']['inbox_guard']=False
        q={**self.request(st),'editor':'client-a'}
        out,calls,_=self.run_send(st,[q],{'id':'own-1'})
        token=out[0]['inbox']
        self.assertNotEqual(token['version'],q['inbox']['version'])
        self.assertTrue(token['manual_followup'])
        self.assertNotIn('a',st['open'])
        follow={**q,'rid':'follow','text':'Additional reply','inbox':token}
        out,calls,_=self.run_send(st,[follow],{'id':'own-2'})
        self.assertEqual(len(calls),1)
        self.assertEqual(out[0]['kind'],'sent')
        self.assertNotEqual(out[0]['inbox']['version'],token['version'])
        self.assertTrue(out[0]['inbox']['manual_followup'])
        self.assertNotIn('a',st['open'])

    def test_duplicate_receipt_requires_same_payload_and_returns_current_collector_token(self):
        st=state(); q={**self.request(st),'editor':'client-a'}
        sent,_,_=self.run_send(st,[q],{'id':'own-1'})
        out,calls,_=self.run_send(st,[{**q,'rid':'same-replay'}],{'id':'must-not-submit'})
        self.assertFalse(calls)
        self.assertEqual(out[0]['kind'],'send_duplicate')
        self.assertEqual(out[0]['inbox'],sent[0]['inbox'])
        self.assertEqual(out[0]['submitted_inbox'],q['inbox'])
        out,calls,_=self.run_send(st,[{**q,'rid':'different-payload','text':'Different additional reply'}],{'id':'must-not-submit'})
        self.assertFalse(calls)
        self.assertEqual(out[0]['kind'],'send_blocked')
        self.assertNotIn('receipt',out[0])

    def test_lost_sent_post_replay_returns_persisted_receipt_and_next_token_without_resending(self):
        st=state(); q={**self.request(st),'editor':'client-a'}
        sent,_,_=self.run_send(st,[q],{'id':'own-1'})
        st=json.loads(json.dumps(st))
        out,calls,_=self.run_send(st,[q],{'id':'must-not-submit'})
        self.assertFalse(calls)
        self.assertEqual(out[0]['kind'],'send_duplicate')
        self.assertEqual(out[0]['receipt']['id'],'own-1')
        self.assertEqual(out[0]['inbox'],sent[0]['inbox'])
        out,calls,_=self.run_send(st,[{**q,'text':'Different intent with reused ID'}],{'id':'must-not-submit'})
        self.assertFalse(calls)
        self.assertEqual(out[0]['kind'],'send_blocked')

    def test_followup_requires_manual_current_token_and_respects_shared_hold(self):
        st=state(); q={**self.request(st),'editor':'client-a'}
        out,_,_=self.run_send(st,[q],{'id':'own-1'})
        follow={**q,'text':'Additional reply','inbox':out[0]['inbox']}
        for extra in ({'automatic':True},{'editor':None}):
            request={**follow,**extra,'rid':'invalid-'+str(extra)}
            out,calls,_=self.run_send(st,[request],{'id':'must-not-submit'})
            self.assertFalse(calls)
            self.assertEqual(out[0]['kind'],'send_blocked')
        token=self.edit(st,editor='client-b',rid='other-editor')
        out,calls,_=self.run_send(st,[{**follow,'rid':'conflict','inbox':token}],{'id':'must-not-submit'})
        self.assertFalse(calls)
        self.assertEqual(out[0]['kind'],'send_blocked')

    def test_new_incoming_source_invalidates_closed_item_manual_followup_even_with_refreshed_token(self):
        st=state(); q={**self.request(st),'editor':'client-a'}
        self.run_send(st,[q],{'id':'own-1'})
        self.new_source(st)
        token=delivery.context(st,'a')
        self.assertFalse(token['manual_followup'])
        out,calls,_=self.run_send(st,[{**q,'rid':'after-new-inbound','inbox':token}],{'id':'must-not-submit'})
        self.assertFalse(calls)
        self.assertEqual(out[0]['kind'],'send_blocked')

    def test_followup_uncertainty_survives_restart_without_fresh_token_or_retry(self):
        st=state(); q={**self.request(st),'editor':'client-a'}
        out,_,_=self.run_send(st,[q],{'id':'own-1'})
        st=json.loads(json.dumps(st))
        follow={**q,'rid':'follow','text':'Additional reply','inbox':out[0]['inbox']}
        out,calls,_=self.run_send(st,[follow],None,TimeoutError('unknown submission'))
        self.assertEqual(len(calls),1)
        self.assertEqual(out[-1]['kind'],'send_uncertain')
        self.assertEqual(out[-1]['inbox']['version'],follow['inbox']['version'])
        self.assertFalse(out[-1]['inbox']['manual_followup'])
        st=json.loads(json.dumps(st))
        self.assertFalse(self.run_send(st,[{**follow,'rid':'retry'}],{'id':'must-not-submit'})[1])

    def test_followup_preflight_verifies_latest_own_receipt_against_actual_account_and_body(self):
        from unittest.mock import Mock
        st=state(); st['refs']['a']['msg']='original-source'
        # The canonical source ref includes the exact incoming message ID.
        delivery.observe(st,{**incoming(),'ref':st['refs']['a']})
        q={**self.request(st),'editor':'client-a'}
        out,_,_=self.run_send(st,[q],{'id':'own-1'})
        follow={**q,'rid':'follow','inbox':out[0]['inbox'],'text':'Additional reply'}
        anchor={'id':'own-1','messageType':'message','createdDateTime':'2026-10-15T12:01:00Z',
                'from':{'user':{'id':'account-a'}},'body':{'content':'<p>Verified reply</p>'}}
        for change in ('none','account','missing','sender','body','deleted','media','new-incoming','new-owner','bad-time'):
            rows=[copy.deepcopy(anchor)]
            if change=='missing': rows=[]
            elif change=='sender': rows[0]['from']['user']['id']='other'
            elif change=='body': rows[0]['body']['content']='Edited outside collector'
            elif change=='deleted': rows[0]['deletedDateTime']='2026-10-15T12:02:00Z'
            elif change=='media': rows[0]['attachments']=[{'id':'attachment'}]
            elif change=='bad-time': rows[0]['createdDateTime']='unknown'
            elif change in ('new-incoming','new-owner'):
                rows.insert(0,{**anchor,'id':'later','createdDateTime':'2026-10-15T12:02:00Z',
                               'from':{'user':{'id':'other' if change=='new-incoming' else 'account-a'}}})
            mcp=Mock();mcp.call.side_effect=[{'id':'account-b' if change=='account' else 'account-a'},{'value':rows}]
            reader=type('Reader',(),{'mcp':mcp})()
            with self.subTest(change=change):
                if change=='none': main.preflight_guarded(st,reader,follow)
                else:
                    with self.assertRaises(ValueError): main.preflight_guarded(st,reader,follow)

    def test_actual_collector_followups_verify_each_own_graph_source_and_reject_unseen_new_inbound(self):
        from unittest.mock import Mock
        st=state(); st['cfg']['inbox_guard']=False
        ref={'chat':'chat-a','msg':'original-source'};st['refs']['a']=ref
        delivery.observe(st,{**incoming(),'ref':ref})
        rows=[{'id':ref['msg'],'messageType':'message','createdDateTime':incoming()['at'],
               'from':{'user':{'id':'counterpart'}},'body':{'content':'Verified facts'}}]
        commits=[];saved=[];out=[]
        def graph(tool,args,**kw):
            if tool=='get-current-user': return {'id':'account-a'}
            if tool=='list-chat-messages': return {'value':copy.deepcopy(rows)}
            self.assertEqual(tool,'send-chat-message')
            self.assertEqual(args['chatId'],'chat-a')
            self.assertTrue(any(c['state']=='claimed' for c in saved[-1]['inbox_delivery']['claims'].values()))
            mid='own-'+str(len(commits)+1)
            commits.append(mid)
            rows.insert(0,{'id':mid,'messageType':'message',
                'createdDateTime':f'2026-10-15T12:0{len(commits)}:00Z',
                'from':{'user':{'id':'account-a'}},'body':args['body']['body']})
            return {'id':mid,'chatId':'chat-a'}
        reader=type('Reader',(),{'mcp':Mock()})()
        reader.mcp.call.side_effect=graph
        with patch.object(main,'save',side_effect=lambda s:saved.append(copy.deepcopy(s))):
            first={**self.request(st),'editor':'client-a','quote':'Verified facts','reply_to':'original-source'}
            main.send_replies(st,reader,[first],out.append)
            token=next(d['inbox'] for d in out if d['kind']=='sent')
            second={**first,'rid':'follow','text':'Additional  reply\n\nWith another line','inbox':token}
            main.send_replies(st,reader,[second],out.append)
            sent=[d for d in out if d['kind']=='sent']
            self.assertEqual(len(sent),2)
            self.assertEqual(commits,['own-1','own-2'])
            self.assertTrue(sent[-1]['inbox']['manual_followup'])
            rows.insert(0,{'id':'new-inbound','messageType':'message','createdDateTime':'2026-10-15T12:03:00Z',
                           'from':{'user':{'id':'counterpart'}},'body':{'content':'New verified facts'}})
            main.send_replies(st,reader,[{**second,'rid':'after-unseen-inbound','inbox':sent[-1]['inbox']}],out.append)
            self.assertEqual(commits,['own-1','own-2'])
            self.assertEqual(out[-1]['kind'],'send_blocked')
            self.assertNotIn('a',st['open'])

    def test_new_facts_and_destination_change_refuse_old_version(self):
        for change in ('new-message','same-item','account','destination'):
            st = state(); q = self.request(st)
            if change=='new-message': delivery.observe(st,incoming('b','Later facts'))
            elif change=='same-item': delivery.observe(st,incoming(text='Changed facts'))
            elif change=='account': st['me']['id']='account-b'
            else: st['refs']['a']={'chat':'chat-b'}
            out,calls,_ = self.run_send(st,[q],{'id':'x'})
            self.assertEqual(calls,[],change)
            self.assertFalse(any(p['kind']=='sent' for p in out))

    def test_missing_receipt_and_timeout_remain_uncertain_never_answered(self):
        for result,error in ((None,None),('ok',None),({'success':True},None),(None,TimeoutError('after submission'))):
            st=state(); q=self.request(st)
            out,calls,_=self.run_send(st,[q],result,error)
            self.assertEqual(len(calls),1)
            self.assertFalse(any(p['kind'] in ('sent','answered') for p in out))
            self.assertEqual(out[-1]['kind'],'send_uncertain')
            st=json.loads(json.dumps(st))
            q['rid']='retry-new-id'
            self.assertEqual(self.run_send(st,[q],{'id':'x'})[1],[])
            self.assertIn('a',st['open'])

    def test_new_facts_do_not_release_an_uncertain_conversation_claim(self):
        st=state()
        self.run_send(st,[self.request(st)],None,TimeoutError('unknown'))
        delivery.observe(st,incoming(text='New facts'))
        self.assertEqual(self.run_send(st,[self.request(st,'new-version')],{'id':'x'})[1],[])

    def test_deferred_request_keeps_version_and_rechecks_new_facts_at_due_time(self):
        from datetime import datetime,timezone
        st=state(); q={**self.request(st),'at':'2030-01-01T08:00:00Z'}
        with patch.object(main,'save'),patch.object(main,'deliver') as send:
            main.send_replies(st,type('Reader',(),{})(),[q],lambda _:None,
                              datetime(2026,1,1,tzinfo=timezone.utc))
            self.assertEqual(st['later'][q['rid']]['inbox'],q['inbox'])
            delivery.observe(st,incoming(text='Later source facts'))
            main.send_replies(st,type('Reader',(),{})(),[],lambda _:None,
                              datetime(2031,1,1,tzinfo=timezone.utc))
            send.assert_not_called()

    def test_immediate_source_read_checks_actual_account_and_newer_messages(self):
        from unittest.mock import Mock
        item=incoming(); item['ref']['msg']='source-id'
        st={'me':{'id':'account-a'},'refs':{'a':item['ref']}}
        delivery.observe(st,item)
        original={'id':'source-id','messageType':'message','createdDateTime':item['at'],
                  'from':{'user':{'id':'counterpart'}},'body':{'content':'Verified facts'}}
        for change in ('none','quote','account','source-text','new-incoming','new-owner','missing','file'):
            rows=[copy.deepcopy(original)]
            if change=='source-text': rows[0]['body']['content']='Changed source'
            # ответ с цитатой — вложение messageReference, не файл (16.10, p404553: ответ Паше держался «source changed»)
            if change=='quote': rows[0]['attachments']=[{'contentType':'messageReference','content':'{}'}]
            if change=='file': rows[0]['attachments']=[{'contentType':'reference','name':'a.pdf'}]
            if change in ('new-incoming','new-owner'):
                rows.insert(0,{**original,'id':'later-id','createdDateTime':'2026-10-15T12:01:00Z',
                               'from':{'user':{'id':'account-a' if change=='new-owner' else 'counterpart'}}})
            if change=='missing': rows=[]
            mcp=Mock(); mcp.call.side_effect=[{'id':'account-b' if change=='account' else 'account-a'},
                                            {'value':rows,'@odata.nextLink':'older-page'}]
            reader=type('Reader',(),{'mcp':mcp})()
            with self.subTest(change=change):
                if change in ('none','quote'): main.preflight_guarded(st,reader,{'id':'a'})
                else:
                    with self.assertRaises(ValueError): main.preflight_guarded(st,reader,{'id':'a'})

    def test_automatic_reply_respects_current_contact_hours_before_transport(self):
        from datetime import datetime,timezone
        st=state(); st['hours']={'from':'08:00','to':'20:00','weekends':False}
        q=self.request(st,'auto',True); out=[]
        with patch.object(main,'save'),patch.object(main,'preflight_guarded'),patch.object(main,'deliver') as send, \
                patch.object(main.hours,'local',side_effect=lambda now:now):
            main.send_replies(st,None,[q],out.append,datetime(2026,10,17,12,tzinfo=timezone.utc))
            send.assert_not_called()
        self.assertEqual(out[0]['kind'],'scheduled')
        self.assertEqual(out[0]['held'],'hours')
        self.assertIn(q['rid'],st['later'])

    def test_preflight_failure_is_not_silently_retried_from_journal_after_restart(self):
        st=state(); q=self.request(st)
        out=[]
        with patch.object(main,'save'),patch.object(main,'preflight_guarded',side_effect=OSError('unavailable')), \
                patch.object(main,'deliver') as send:
            main.send_replies(st,None,[q],out.append)
            send.assert_not_called()
        self.assertEqual(out[-1]['kind'],'send_blocked')
        self.assertFalse(st['inbox_delivery']['claims'])
        st=json.loads(json.dumps(st))
        self.assertEqual(self.run_send(st,[q],{'id':'must-not-send'})[1],[])
        self.assertEqual(len(self.run_send(st,[{**q,'rid':'deliberate-new-request'}],{'id':'verified-id'})[1]),1)

    def test_cancel_scheduled_version_preserves_item_and_owns_hold(self):
        from datetime import datetime,timezone
        st=state(); q={**self.request(st),'at':'2030-01-01T08:00:00Z','editor':'client-a'}
        out=[]
        with patch.object(main,'save'),patch.object(main,'deliver') as send:
            main.send_replies(st,None,[q,{'cancel':q['rid'],'editor':'client-a'}],out.append,
                              datetime(2026,1,1,tzinfo=timezone.utc))
            send.assert_not_called()
        self.assertIn('a',st['open'])
        self.assertTrue(delivery.context(st,'a')['held'])
        self.assertEqual(delivery.context(st,'a')['holder'],'client-a')
        self.assertNotIn(q['rid'],st['later'])

    def test_precommit_claim_survives_crash(self):
        st=state(); q=self.request(st)
        delivery.claim(st,q)
        st=json.loads(json.dumps(st)); q['rid']='second'
        self.assertEqual(self.run_send(st,[q],{'id':'x'})[1],[])

    def test_guarded_replay_keeps_the_original_target_and_refuses_a_changed_one(self):
        # 17.10 (codex m479400): повтор исходного rid на защищённом пути отдавал итог без target (веб его отбрасывал), а
        # тот же rid с другим target получал прежний успех. Теперь target — часть заявки: повтор несёт исходный,
        # другой target — отказ; повторной отправки нет ни в одном случае
        st=state(); target=main.target_of(st['refs']['a'])
        q={**self.request(st),'editor':'client','target':target}
        out,calls,_=self.run_send(st,[q],{'id':'receipt-1'})
        self.assertEqual((len(calls),out[0]['kind'],out[0].get('target')),(1,'sent',target))
        st=json.loads(json.dumps(st))
        same,c1,_=self.run_send(st,[q],{'id':'never'})
        moved,c2,_=self.run_send(st,[{**q,'target':'other'}],{'id':'never'})
        legacy,c3,_=self.run_send(st,[{k:v for k,v in q.items() if k!='target'}],{'id':'never'})
        self.assertEqual(c1+c2+c3,[])
        self.assertEqual((same[0]['kind'],same[0].get('target')),('send_duplicate',target))
        self.assertEqual((moved[0]['kind'],moved[0].get('target')),('send_blocked',target))
        self.assertEqual(legacy[0]['kind'],'send_blocked')

    def test_legacy_client_cannot_enable_auto_send_and_outside_teams_sends_once_plainly(self):
        st=state(); st['cfg']['inbox_guard']=False
        self.assertEqual(self.run_send(st,[self.request(st,'auto',True)],{'id':'x'})[1],[])
        # вне Teams квитанции нет — автоответ обычной отправкой, один раз (Иван q465184, 17.10: «Разрешить вне Teams»)
        st=state(); st['refs']['a']={'tg':'peer'}; st['open']={'a':['x','t']}
        q=self.request(st,'auto',True)
        out,calls,_=self.run_send(st,[q,dict(q)],{'id':'x'})
        self.assertEqual(len(calls),1)
        self.assertEqual(out[0]['kind'],'sent')
        self.assertFalse(delivery.store(st)['claims'])
        st['cfg']['inbox_guard']=False
        self.assertEqual(self.run_send(st,[{**q,'rid':'auto2'}],{'id':'x'})[1],[])


class PrivateInstruction(unittest.TestCase):
    def test_legacy_settings_preserve_guard_without_reposting_config_forever(self):
        st={'cfg':{'inbox_guard':True,'prompt':'Kept owner guidance'}}
        choice=type('Choice',(),{'settings':{'signature':'','autodraft':True,'prompt':'Kept owner guidance'},'hours':None})()
        out=[]
        main.settings(st,choice,out.append)
        main.settings(st,choice,out.append)
        self.assertTrue(st['cfg']['inbox_guard'])
        self.assertEqual(sum(p['kind']=='config' for p in out),1)

    def test_choice_preserves_private_instruction_and_intentional_empty_draft(self):
        choice=main.Choice('/unused')
        event={'type':'ext.post','seq':10,'ts':1000,'data':{'plugin':main.NAME,'channel':'web','owner':True,
            'text':json.dumps({'kind':'ask','what':'draft','rid':'r','post':'p123','instruction':'Verified owner direction','draft':''})}}
        choice.line(json.dumps(event).encode())
        q,=choice.take_sends()
        self.assertEqual(q['instruction'],'Verified owner direction')
        self.assertIn('draft',q)
        self.assertEqual(q['draft'],'')

    def test_legacy_private_comment_refuses_unbound_editor_replacement(self):
        out,told=[],[]
        with patch.object(main,'save'),patch.object(main,'deliver',side_effect=AssertionError('send forbidden')):
            main.ask_hub({'cfg':{}},{'ask':'draft','rid':'r','post':'p123','instruction':'Verified direction','draft':''},out.append,told.append,1000)
        self.assertEqual(told,[])
        self.assertEqual(out[0]['kind'],'ask_failed')
        self.assertNotIn('instruction',out[0])


if __name__=='__main__': unittest.main()
