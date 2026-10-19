"""Current-version delivery claims owned by the single serialized collector.

All mutations must be persisted by the caller before any transport call. A claim
without a receipt is unresolved after restart, never permission to retry. Tokens
contain no destination or message text; accepted source records retain the facts.
"""
import hashlib
import json
import os
from contextlib import contextmanager


@contextmanager
def writer_lock(path):
    """One writer across collector processes, not merely one in-memory queue."""
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,'a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            import fcntl
        except ImportError:
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode()).hexdigest()


def store(st):
    db = st.setdefault('inbox_delivery', {'items':{}, 'threads':{}, 'claims':{}, 'controls':{}})
    if 'editors' not in db:
        # Upgrade candidate row-scoped holds without dropping any active holder.
        # Multiple legacy holders remain conflicting until each releases its own hold.
        editors = {}
        for row in db['items'].values():
            edit = editors.setdefault(row['thread'], {'edit_version':0, 'holders':[]})
            edit['edit_version'] = max(edit['edit_version'], row.get('edit_version',0))
            if row.get('held') and row.get('holder') not in edit['holders']:
                edit['holders'].append(row.get('holder'))
            for field in ('held','holder','edit_version'):
                row.pop(field,None)
        db['editors'] = editors
    return db


def editor_state(st, row):
    return store(st)['editors'].setdefault(row['thread'], {'edit_version':0, 'holders':[]})


def identity(st, ref):
    """Only the existing native Teams adapter currently returns a checked receipt.
    Other adapters have no proven account/receipt contract and fail before IO.
    """
    account = (st.get('me') or {}).get('id')
    if not account or not isinstance(ref, dict) or any(ref.get(k) for k in ('wa','tg','mail')):
        raise ValueError('Verified account and receipt-capable source required')
    if ref.get('chat'):
        destination = ['chat', ref['chat']]
    elif all(ref.get(k) for k in ('team','channel','root')):
        destination = ['channel', ref['team'], ref['channel'], ref['root']]
    else:
        raise ValueError('Verified conversation required')
    return digest(['teams', account, destination])


def observe(st, item):
    """Called on canonical incoming facts, including same-item text corrections."""
    try:
        thread = identity(st, item.get('ref'))
    except ValueError:
        return None
    db = store(st)
    key = item['key']
    facts = digest([thread, key, item.get('at'), item.get('text'), item.get('media'), item.get('links'),item['ref']])
    row = db['items'].get(key)
    if row and row['facts'] == facts and row['thread'] == thread:
        return context(st,key)
    db['threads'][thread] = db['threads'].get(thread,0) + 1
    # Old identities retain their claims and holds; new identities never inherit them.
    db['items'][key] = {'thread':thread, 'facts':facts, 'ref':item['ref'],
                        'source_at':item.get('at'),'source_text':item.get('text'),
                        'source_media':bool(item.get('media') or item.get('links'))}
    return context(st,key)


def context(st, key):
    db = store(st)
    row = db['items'].get(key)
    if not row:
        return None
    edit = editor_state(st,row)
    holders = edit['holders']
    version = [row['thread'],row['facts'],db['threads'].get(row['thread'])]
    followup = row.get('followup')
    if followup:
        version.append(followup)
    manual = bool(followup and followup['thread_version'] == db['threads'].get(row['thread'])
                  and not any(c['thread']==row['thread'] and c['state'] in ('claimed','uncertain')
                              for c in db['claims'].values()))
    return {'v':1, 'version':digest(version), 'manual_followup':manual,
            'edit_version':edit['edit_version'], 'held':bool(holders),
            'holder':holders[0] if len(holders)==1 else None}


def current(st, q):
    row = store(st)['items'].get(q.get('id'))
    token = q.get('inbox')
    ctx = context(st,q.get('id'))
    if not row or not isinstance(token,dict) or token.get('v') != 1 or not ctx or any(
            token.get(k) != ctx[k] for k in ('version','edit_version')):
        raise ValueError('Inbox changed; refresh the current item before acting')
    ref = (st.get('refs') or {}).get(q['id'])
    if identity(st,ref) != row['thread'] or digest(ref) != digest(row['ref']):
        raise ValueError('Account or destination changed')
    return row,ctx


def control(st, q):
    """Owner-only CAS hold/release, independent of presence and wall clock."""
    db = store(st)
    editor=q.get('editor')
    if not isinstance(editor,str) or not editor or len(editor)>100:
        raise ValueError('Stable client editor identity required')
    fingerprint=digest({k:q[k] for k in ('id','inbox','action','editor') if k in q})
    if q.get('rid') in db['controls']:
        if db['controls'][q['rid']] != {'id':q['id'],'input':fingerprint}:
            raise ValueError('Editor request ID was reused with different input')
        return context(st,q['id'])
    row,ctx = current(st,q)
    if q.get('action') not in ('hold','release'):
        raise ValueError('Explicit hold or release action required')
    edit = editor_state(st,row)
    holders = edit['holders']
    if holders and editor not in holders and holders != [None]:
        raise ValueError('Another client holds this editor; retain local text')
    if holders == [None] and q['action']=='release':
        raise ValueError('Adopt the unowned cancellation hold before releasing it')
    if q['action']=='hold' and any(h not in (None,editor) for h in holders):
        raise ValueError('Another client holds this editor; retain local text')
    if ctx['version'] in db['claims'] and db['claims'][ctx['version']]['state'] != 'held':
        raise ValueError('Delivery already claimed; reconcile its outcome')
    edit['holders'] = [editor] if q['action']=='hold' else [h for h in holders if h != editor]
    edit['edit_version'] += 1
    db['controls'][q['rid']] = {'id':q['id'],'input':fingerprint}
    return context(st,q['id'])


def cancel_hold(st, key, editor=None):
    """A canceled deferred send preserves the whole conversation's editor exclusion."""
    row = store(st)['items'].get(key)
    if not row:
        return None
    edit = editor_state(st,row)
    if not edit['holders']:
        edit['holders'] = [editor if isinstance(editor,str) and 0 < len(editor) <= 100 else None]
    edit['edit_version'] += 1
    return context(st,key)


def check(st, q):
    row,ctx = current(st,q)
    if q.get('automatic') and not (st.get('cfg') or {}).get('inbox_guard'):
        raise ValueError('Shared editor protection is not activated')
    if ctx['held'] and (q.get('automatic') or not q.get('editor') or q.get('editor') != ctx.get('holder')):
        raise ValueError('Owner is editing or directing this conversation; explicit release required')
    if ctx['manual_followup'] and (q.get('automatic') or not isinstance(q.get('editor'),str)
                                  or not 0 < len(q['editor']) <= 100):
        raise ValueError('A manual follow-up requires a stable client editor')
    if q['id'] not in (st.get('open') or {}) and not ctx['manual_followup']:
        raise ValueError('The canonical source item is no longer open')
    if not isinstance(q.get('text'),str) or not q['text'].strip() or q.get('files'):
        raise ValueError('A supported nonempty text reply is required')
    claims = store(st)['claims']
    if any(c['thread'] == row['thread'] and c['state'] in ('claimed','uncertain') for c in claims.values()):
        raise ValueError('This conversation has an unresolved delivery; reconcile it first')
    key = ctx['version']
    if key in claims and claims[key]['state'] != 'held':
        raise ValueError('This version already has a delivery claim; reconcile its outcome')
    return key,row


def claim(st,q):
    key,row=check(st,q)
    submitted = context(st,q['id'])
    store(st)['claims'][key] = {'rid':q['rid'], 'id':q['id'], 'state':'claimed',
                   'thread':row['thread'], 'submitted_inbox':submitted, 'payload':payload(q),
                   **({'target':q['target']} if q.get('target') else {})}  # adress the client saw (codex m479400)
    edit = editor_state(st,row)
    if edit['holders']:  # explicit matching-client manual Send: consume hold+claim together
        edit['holders']=[]
        edit['edit_version']+=1
    return key


def finish(st, key, state, receipt=None):
    row = store(st)['claims'][key]
    row['state'] = state
    if receipt is not None:
        row['receipt'] = receipt


def confirmed(st, key, receipt, source_text):
    """Advance only from this collector's verified transport receipt, never client input."""
    db = store(st)
    claim = db['claims'][key]
    row = db['items'][claim['id']]
    if claim['state'] != 'claimed' or receipt.get('source') != 'teams' \
            or receipt.get('destination') != digest(row['ref']) or claim['thread'] != row['thread']:
        raise ValueError('Confirmed delivery does not match its source claim')
    finish(st,key,'sent',receipt)
    db['threads'][row['thread']] += 1
    row['followup'] = {'id':receipt['id'], 'text':source_text,
                       'thread_version':db['threads'][row['thread']]}


def payload(q):
    return digest([q.get('text'),q.get('files'),q.get('reply_to'),q.get('quote')])


def receipt(result, ref):
    """A Graph message ID returned by this call, not empty_ok/exit0/stdout ok."""
    if not isinstance(result,dict) or not isinstance(result.get('id'),str) or not result['id'].strip():
        raise ValueError('Transport returned no verifiable message receipt')
    if result.get('chatId') and result['chatId'] != ref.get('chat'):
        raise ValueError('Transport receipt belongs to a different conversation')
    return {'source':'teams', 'id':result['id'], 'destination':digest(ref)}


def previous(st,q):
    token=q.get('inbox') or {}
    claim=store(st)['claims'].get(token.get('version')) if isinstance(token,dict) else None
    row=store(st)['items'].get(q.get('id'))
    if not claim or not row or claim['id'] != q.get('id') or claim.get('payload') != payload(q):
        return None
    try:
        same=identity(st,(st.get('refs') or {}).get(q['id'])) == claim['thread']
    except ValueError:
        return None
    if not same:
        return None
    pinned = {'target':claim['target']} if claim.get('target') else {}
    if claim.get('target') != q.get('target'):  # same rid, other conversation: never inherit the original outcome
        return {'kind':'send_blocked','id':q['id'],'rid':q['rid'],'error':'Request ID reused with different input',**pinned}
    return {**pinned,'kind':'send_duplicate','id':q['id'],'rid':q['rid'],'original_rid':claim['rid'],
            'version':token['version'],'state':'uncertain' if claim['state']=='claimed' else claim['state'],
            'inbox':context(st,q['id']),
            **({'submitted_inbox':claim['submitted_inbox']} if claim.get('submitted_inbox') else {}),
            **({'receipt':claim['receipt']} if claim.get('receipt') else {})}
