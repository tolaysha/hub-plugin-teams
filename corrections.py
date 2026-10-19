"""Reference-bound Inbox corrections. Accepted core posts are the authority.

This module never reads source services, sends replies or rewrites journal posts.
"""
import json
import re


def feed(state_dir, name):
    from core import journal
    return journal.load_state(state_dir).get('feeds', {}).get(name, [])


def plan_reopen(posts, source, corrects, name='teams'):
    """Return a plugin fact, None if already applied, or refuse a stale correction.

    Both references must still exist in the accepted feed. Missing historical
    evidence fails closed, rather than guessing from a display name or local state.
    """
    if not all(isinstance(p, str) and re.fullmatch(r'p\d+', p) for p in (source, corrects)):
        raise ValueError('Exact source and answered post references required')
    trusted = []
    for p in sorted(posts, key=lambda p: int(p['id'][1:])):
        if p.get('by') != f'плагин {name}':
            continue
        try:
            d = json.loads(p['text'])
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict):
            trusted.append((p['id'], d))
    by_post = dict(trusted)
    msg, closed = by_post.get(source, {}), by_post.get(corrects, {})
    key, contact = msg.get('id'), msg.get('contact')
    if (msg.get('kind') != 'msg' or not key or not contact or not msg.get('reply')
            or closed.get('kind') != 'answered' or closed.get('id') != key
            or int(corrects[1:]) <= int(source[1:])):
        raise ValueError('Source and false answered posts do not match')
    closure, latest, applied = None, None, False
    for pid, d in trusted:
        if d.get('kind') == 'msg' and d.get('contact') == contact:
            latest = pid
        if d.get('id') != key:
            continue
        if d.get('kind') == 'sent':
            raise ValueError('A successful send cannot be reopened by a closure correction')
        if d.get('kind') == 'answered' or d.get('kind') == 'msg' and d.get('answered'):
            closure = pid
        if d.get('kind') == 'reopened' and d.get('post') == source and d.get('corrects') == corrects:
            applied = True
    if latest != source or closure != corrects:
        raise ValueError('The item or its closure has changed; correction refused')
    if applied:
        return None
    return {'kind': 'reopened', 'id': key, 'post': source, 'corrects': corrects,
            'contact': contact, 'reset_history': True}


def reopen(st, state_dir, name, source, corrects, put):
    posts = feed(state_dir, name)
    event = plan_reopen(posts, source, corrects, name)
    if event is None:
        return False
    key, contact = event['id'], event['contact']
    ref = st.get('refs', {}).get(key) or {}
    # Restoring a card must not silently change its delivery destination.
    if not ref.get('wa') or f"wa:{ref['wa']}:{ref.get('to')}" != contact:
        raise ValueError('Stored reply destination does not match the source item')
    msg = json.loads(next(p['text'] for p in posts if p['id'] == source))
    if not msg.get('at'):
        raise ValueError('Source timestamp unavailable')
    st.setdefault('open', {})[key] = [contact, msg['at']]
    st['hist'] = {k: v for k, v in st.get('hist', {}).items() if not k.startswith(key + '|')}
    put(event)
    return True
