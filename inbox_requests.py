"""Private request/result binding. No model, transport or owner impersonation."""
import json
import secrets

import inbox_delivery as delivery


def hub_identity(snapshot, require_generation=False):
    for name,row in snapshot.get('sessions',{}).items():
        if row.get('kind') == 'hub' and row.get('state') not in ('removed','closed','failed'):
            if require_generation and (not isinstance(row.get('launch_generation'),int)
                    or isinstance(row['launch_generation'],bool) or row['launch_generation']<1
                    or not isinstance(row.get('session_id'),str) or not row['session_id']):
                raise ValueError('Canonical Hub generation unavailable')
            return {'name':name, 'generation':row.get('launch_generation'), 'session_id':row.get('session_id')}
    raise ValueError('Canonical Hub identity unavailable')


def source(posts, post, key, name):
    found = next((p for p in posts if p.get('id') == post and p.get('by') == 'плагин '+name),None)
    try:
        body = json.loads(found['text']) if found else {}
    except (ValueError,TypeError):
        body = {}
    if body.get('kind') != 'msg' or body.get('id') != key or body.get('answered'):
        raise ValueError('Exact current source post required')
    newer = [p for p in posts if p.get('by') == 'плагин '+name and int(p['id'][1:]) > int(post[1:])]
    for p in newer:
        try: d=json.loads(p['text'])
        except (ValueError,TypeError): continue
        if isinstance(d,dict) and d.get('id') == key and d.get('kind') in ('msg','answered','sent','reopened'):
            raise ValueError('Source post changed or closed')
    return body


def begin(st, q, snapshot, posts, name):
    if not isinstance(q.get('instruction'),str) or not q['instruction'].strip() or len(q['instruction'])>2000:
        raise ValueError('A nonempty private instruction of at most 2000 characters is required')
    requests=st.setdefault('inbox_requests',{})
    request_digest=delivery.digest({k:q[k] for k in ('id','rid','post','inbox','instruction','draft','editor') if k in q})
    if q['rid'] in requests:
        row=requests[q['rid']]
        if row['input_digest'] != request_digest:
            raise ValueError('Request ID was reused with different private input')
        return row if row['state']=='pending' and not row.get('dispatched') else None
    delivery.current(st,q)
    source(posts,q['post'],q['id'],name)
    hub=hub_identity(snapshot,True)
    ctx=delivery.control(st,{**q,'action':'hold'})
    request={'id':q['id'],'post':q['post'],'rid':q['rid'],'inbox':ctx,
             'editor':q['editor'],
             'hub':hub,'nonce':secrets.token_urlsafe(24),'state':'pending','input_digest':request_digest,
             'instruction':q['instruction'], **({'draft':q['draft']} if 'draft' in q else {})}
    requests[q['rid']]=request
    return request


def result(st, q, snapshot, posts, name):
    row=st.get('inbox_requests',{}).get(q.get('rid'))
    if not row or row['state'] not in ('pending','proposed'):
        raise ValueError('No pending revision request')
    if (q.get('_author') != row['hub']['name'] or hub_identity(snapshot,True) != row['hub']
            or q.get('nonce') != row['nonce'] or q.get('post') != row['post']):
        raise ValueError('Revision author, generation or request does not match')
    source(posts,row['post'],row['id'],name)
    delivery.current(st,row)
    if not all(isinstance(q.get(k),str) for k in ('text','context','next_action')):
        raise ValueError('Structured editable reply, context and next action required')
    fingerprint=delivery.digest([q[k] for k in ('text','context','next_action')])
    if row['state']=='proposed':
        if row['result_digest'] != fingerprint:
            raise ValueError('This request already has a different proposal')
        return row['proposal']  # durable outbox replay after save-before-post crash
    # A plugin-authored proposal has its own explicit kind. Raw session JSON is
    # not a verified result and cannot replace an editor via this contract.
    proposal={'kind':'draft_proposal','id':row['id'],'post':row['post'],'rid':row['rid'],
              'inbox':row['inbox'],'editor':row['editor'], 'requires_apply':True,
              **{k:q[k] for k in ('text','context','next_action')}}
    if len(json.dumps(proposal,ensure_ascii=False)) > 1900:
        raise ValueError('Proposal exceeds the channel envelope; shorten it')
    row['state']='proposed'
    row['result_digest']=fingerprint
    row['proposal']=proposal
    return proposal
