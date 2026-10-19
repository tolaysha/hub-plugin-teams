import { T } from "/static/js/ui-text.js";

// One contextual menu for every message row. The resolver supplies current identity,
// so an open menu can never act on a rebound conversation or a changed history row.
export function messageMenus(root, resolve, report, {selector='.tm-line', attribute='message', label=null}={}) {
  const controller=new AbortController(), options={signal:controller.signal};
  let menu=null, anchor=null, selected=null, timer=null, touch=null, previousFocus=null;
  const liveRow=id=>[...root.querySelectorAll(selector)].find(row=>row.dataset[attribute]===id);
  function close(focus=false) {
    clearTimeout(timer);timer=null;touch=null;
    const target=previousFocus?.isConnected && previousFocus!==document.body ? previousFocus
      : anchor?.isConnected ? anchor : liveRow(selected?.id);
    menu?.remove();menu=null;selected=null;
    if(focus)target?.focus({preventScroll:true});
    anchor=null;previousFocus=null;
  }
  const current=()=>selected && resolve(selected.id)?.identity===selected.identity;
  function open(row,x,y) {
    row=liveRow(row.dataset[attribute]);
    const found=row && resolve(row.dataset[attribute]);if(!found?.items.length){close();return;}
    const prior=menu?.contains(document.activeElement) ? previousFocus : document.activeElement;
    close();anchor=row;selected={id:row.dataset[attribute],identity:found.identity};
    previousFocus=prior;
    menu=document.createElement('div');menu.className='menu tm-message-menu';
    menu.setAttribute('role','menu');menu.setAttribute('aria-label',label || T('Действия с сообщением','Message actions'));
    menu.setAttribute('popover','manual');
    const buttons=found.items.map(item=>{
      const b=document.createElement('button');b.type='button';b.className='menu-item';b.tabIndex=-1;
      b.setAttribute('role','menuitem');b.textContent=item.label;if(item.icon)b.prepend(item.icon);
      b.addEventListener('click',async()=>{
        if(!current()){close(true);return;}
        close(true);
        try{await item.run();}catch{report(T('Действие не выполнено. Повтори запрос.','Action failed. Try again.'));}
      });menu.append(b);return b;
    });
    menu.addEventListener('keydown',e=>{
      const i=buttons.indexOf(document.activeElement), step={ArrowDown:1,ArrowUp:-1}[e.key];
      const next=step ? (i+step+buttons.length)%buttons.length : e.key==='Home' ? 0 : e.key==='End' ? buttons.length-1 : -1;
      if(next>=0){e.preventDefault();buttons[next].focus();}
      if(e.key==='Tab')close(true);
    });
    document.body.append(menu);menu.showPopover?.();
    const r=menu.getBoundingClientRect();
    menu.style.left=Math.max(8,Math.min(x,innerWidth-r.width-8))+'px';
    menu.style.top=Math.max(8,Math.min(y,innerHeight-r.height-8))+'px';
    buttons[0]?.focus({preventScroll:true});
  }
  function rowFor(e) {
    if(e.target.closest('button,a,input,textarea,video,audio'))return null;
    const row=e.target.closest(selector);return row && root.contains(row) ? row : null;
  }
  root.addEventListener('contextmenu',e=>{const row=rowFor(e);if(!row)return;e.preventDefault();open(row,e.clientX,e.clientY);},options);
  root.addEventListener('keydown',e=>{
    if(e.key!=='ContextMenu' && !(e.shiftKey && e.key==='F10'))return;
    const row=rowFor(e);if(!row)return;e.preventDefault();const r=row.getBoundingClientRect();open(row,r.left+16,r.top+16);
  },options);
  root.addEventListener('pointerdown',e=>{
    if(e.pointerType!=='touch')return;const row=rowFor(e);if(!row)return;
    touch={x:e.clientX,y:e.clientY};clearTimeout(timer);timer=setTimeout(()=>open(row,e.clientX,e.clientY),550);
  },options);
  root.addEventListener('pointermove',e=>{if(touch && Math.hypot(e.clientX-touch.x,e.clientY-touch.y)>10){clearTimeout(timer);touch=null;}},options);
  for(const event of ['pointerup','pointercancel'])root.addEventListener(event,()=>{clearTimeout(timer);touch=null;},options);
  // Dismiss before the row listener arms the next long press on this same event.
  document.addEventListener('pointerdown',e=>{if(menu && !menu.contains(e.target))close();},{...options,capture:true});
  window.addEventListener('keydown',e=>{if(menu && e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close(true);}},{...options,capture:true});
  window.addEventListener('hashchange',()=>close(),options);
  window.addEventListener('resize',()=>close(),options);
  document.addEventListener('scroll',e=>{if(menu && !menu.contains(e.target))close();},{...options,capture:true});
  return {validate(){if(menu && (!root.isConnected || !current()))close(true);},destroy(){close();controller.abort();}};
}
