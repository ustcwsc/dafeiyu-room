import {toV2Card,fromV2Card} from './vendor/cosplay-store.js';
const $=s=>document.querySelector(s);
const sheet=$('#sheet'), contents=$('#contents'), notice=$('#notice');
const titles={diary:'日记本',mood:'心情天气',todo:'待办便签',story:'每日小故事',chat:'和大肥鱼聊聊',provider:'模型设置',role:'角色卡',memory:'记忆簿',mind:'她的心愿'};
let state, panel, busy=false, diaryTab='fish',roleDraft,providerDraft;
const catalogs={};
const html=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function entries(rows, key='body'){
    return rows.map(row=>'<article class="entry"><small>'+html(row.day)+(row.model?' · '+html(row.model):'')+'</small>'+html(row[key])+'</article>').join('');
}
function chatMessage(message){
    const mine=message.role==='user';
    const sources=(message.sources||[]).map((s,i)=>'<a href="'+html(s.url)+'" target="_blank" rel="noopener noreferrer">'+(i+1)+'. '+html(s.title)+'</a>').join('');
    return '<article class="chat-line '+(mine?'outgoing':'incoming')+'" aria-label="'+(mine?'我':'大肥鱼')+'">'+
        (mine?'':'<span class="portrait chat-avatar" aria-hidden="true"></span>')+
        '<div class="chat-bubble">'+html(message.body)+(sources?'<div class="chat-sources">'+sources+'</div>':'')+'</div></article>';
}
async function refresh(){
    const res=await fetch('/api/state',{cache:'no-store'});
    if(!res.ok)throw new Error('暂时读不到小窝的数据。');
    state=await res.json();
    window.dispatchEvent(new CustomEvent('fish-state',{detail:state}));
    $('#day').textContent=new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'}).format(new Date(state.day+'T12:00:00+08:00'));
    $('#providerBtn').textContent=state.providers[state.provider].name+' · 模型';
    const goal=state.thoughts.find(x=>x.state==='active');
    $('#intention').textContent=goal?'想'+goal.title+'　›':'她的心愿　›';
}
function paint(){
    $('#panelTitle').textContent=titles[panel];
    sheet.classList.toggle('chat-sheet',panel==='chat');
    if(panel==='diary'){
        contents.innerHTML='<div class="row tabs">'+[['fish','她的手记'],['mine','我的日记']].map(([id,name])=>'<button data-diary-tab="'+id+'" aria-pressed="'+(id===diaryTab)+'">'+name+'</button>').join('')+'</div>'+(diaryTab==='fish'?'<div class="history">'+(entries(state.fishDiary)||'<p class="hint">她完成第一件心愿后，会在这里留下一页。</p>')+'</div>':'<form data-action="diary"><label>今天这一页<textarea name="body" maxlength="6000" required placeholder="记下一件今天想留下的小事…">'+html(state.diary.find(d=>d.day===state.day)?.body||'')+'</textarea></label><button class="primary">保存这一页</button></form><div class="history">'+entries(state.diary.filter(d=>d.day!==state.day))+'</div>');
    }else if(panel==='mood'){
        const selected=state.moods.find(r=>r.day===state.day)?.weather;
        contents.innerHTML='<div class="panelbody"><div class="row">'+['晴天','微风','多云','小雨','雷阵雨'].map((m,i)=>'<button data-weather="'+m+'" aria-pressed="'+(m===selected)+'">'+['☀','〰','☁','☂','ϟ'][i]+' '+m+'</button>').join('')+'</div></div><div class="history">'+entries(state.moods,'weather')+'</div>';
    }else if(panel==='todo'){
        contents.innerHTML='<form data-action="todo"><label>新便签<input maxlength="200" name="body" required placeholder="写一件要做的事"></label><button class="primary">钉到板上</button></form><div class="list">'+state.todos.map(t=>'<label class="entry check '+(t.done?'done':'')+'"><input type="checkbox" data-id="'+t.id+'" '+(t.done?'checked':'')+'>'+html(t.body)+'<small>'+html(t.author)+'</small></label>').join('')+'</div>';
    }else if(panel==='story'){
        const has=state.stories.some(s=>s.day===state.day);
        contents.innerHTML='<div class="panelbody">'+(has?'':'<button class="primary" data-make>写今天的故事 · '+html(state.providers[state.provider].name)+'</button>')+'<label class="check"><input type="checkbox" data-daily '+(state.daily?'checked':'')+'>每天 20:00 自动生成（北京时间）</label></div><div class="history">'+entries(state.stories)+'</div>';
    }else if(panel==='provider'){
        const id=providerDraft||state.provider,p=state.providers[id];
        const options=[...new Set([p.model,...(catalogs[id]|| (id==='openai'?['gpt-4.1-mini','gpt-4.1','gpt-4o-mini']:['deepseek-flash','deepseek-v4-pro']))])];
        contents.innerHTML='<form data-action="provider"><label>服务商<select id="providers" name="provider">'+Object.entries(state.providers).map(([k,v])=>'<option value="'+k+'" '+(k===id?'selected':'')+'>'+html(v.name)+(v.ready?'':' · 待配置密钥')+'</option>').join('')+'</select></label><label>选择模型<select id="pick-model">'+options.map(m=>'<option>'+html(m)+'</option>').join('')+'<option value="">输入其他模型 ID…</option></select></label><label>模型 ID<input name="model" id="model-id" required maxlength="150" value="'+html(p.model)+'"></label><div class="row"><button type="button" id="sync-models" '+(p.ready?'':'disabled')+'>读取账户模型</button><button class="primary" '+(p.ready?'':'disabled')+'>保存选择</button></div><small>当前使用 '+html(state.providers[state.provider].model)+'</small></form>';
    }else if(panel==='role'){
        const c=roleDraft||state.role;
        contents.innerHTML='<form data-action="role"><label>角色库<select id="role-library">'+state.roles.map(r=>'<option value="'+html(r.id)+'" '+(r.id===c.id?'selected':'')+'>'+html(r.name)+'</option>').join('')+'<option value="" '+(!c.id?'selected':'')+'>新建角色卡…</option></select></label>'+[['name','名字'],['description','身份'],['personality','性格'],['style','说话习惯'],['behavior','爱好与习惯']].map(([k,n])=>'<label>'+n+(k==='name'?'<input required maxlength="100" name="name" value="'+html(c.name||'')+'">':'<textarea rows="2" maxlength="4000" name="'+k+'">'+html(c[k]||'')+'</textarea>')+'</label>').join('')+'<div class="row"><button class="primary">保存并使用</button><button type="button" id="import-role">导入 JSON</button><button type="button" id="export-role">导出 JSON</button></div><input type="file" accept=".json,application/json" id="role-file" hidden></form>';
    }else if(panel==='memory'){
        contents.innerHTML='<form data-action="memory"><label>关于谁或哪里<input name="entity" maxlength="80" required value="来访者"></label><label>想记住的事<input name="body" maxlength="700" required></label><button class="primary">记下来</button></form><div class="history">'+state.memories.map(m=>'<article class="entry"><small>'+html(m.entity)+' · '+html(m.source)+' · '+html(m.day)+'</small>'+html(m.body)+'<button class="quiet" data-forget="'+m.id+'">忘掉</button></article>').join('')+'</div><a class="export" href="/api/memory/graph" download="大肥鱼-记忆图谱.json">导出记忆图谱</a>';
    }else if(panel==='mind'){
        const labels={active:'正在做',queued:'接下来',wish:'想扩展',done:'已完成'};
        contents.innerHTML='<div class="mind-list">'+[...state.thoughts,...state.recent].map(g=>'<article class="entry"><small>'+labels[g.state]+' · '+html(g.source)+'</small><b>'+html(g.title)+'</b><p>'+html(g.result||g.reason)+'</p></article>').join('')+'</div><form data-action="wish"><label>给未来的小窝留个想法<input name="body" maxlength="180" required></label><button>收进愿望簿</button></form><button class="primary reflect" data-reflect>用 '+html(state.providers[state.provider].model)+' 构思一次</button><small>手动调用一次模型，写一页日记、一件待办和一个新愿望。</small>';
    }else if(panel==='chat'){
        contents.innerHTML='<div class="chat-log" role="log" aria-label="聊天记录">'+(state.chat.map(chatMessage).join('')||'<p class="chat-empty">和大肥鱼打个招呼吧</p>')+'</div><form data-action="chat" class="chat-compose"><textarea aria-label="消息" name="body" rows="2" required maxlength="2000" placeholder="发消息…"></textarea><div class="chat-controls"><label><input type="checkbox" name="search">'+(state.provider==='openai'?'联网搜索':'查维基百科')+'</label><button class="primary">发送</button></div></form>';
        const log=contents.querySelector('.chat-log');requestAnimationFrame(()=>{log.scrollTop=log.scrollHeight;});
    }
    contents.inert=busy;
}
let ready=refresh().catch(e=>{$('#day').textContent=e.message;});
async function openPanel(key){
    if(!titles[key]||busy)return;
    await ready;
    if(!state)await refresh();
    panel=key;roleDraft=null;providerDraft=null;notice.textContent='';paint();if(!sheet.open)sheet.showModal();
}
async function save(action,payload){
    if(busy)return;busy=true;contents.inert=true;notice.textContent=['chat','story','reflect'].includes(action)?'大肥鱼正在想…':'正在保存…';
    let pending;
    if(action==='chat'){
        const log=contents.querySelector('.chat-log');
        log.querySelector('.chat-empty')?.remove();
        log.insertAdjacentHTML('beforeend',chatMessage({role:'user',body:payload.body}));
        pending=log.lastElementChild;log.scrollTop=log.scrollHeight;
    }
    try{
        const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const data=await response.json();if(!response.ok)throw new Error(data.error||'保存失败。');
        await refresh();roleDraft=null;paint();notice.textContent=action==='chat'?'':'已保存。';
    }catch(e){pending?.remove();notice.textContent=e.message;if(action==='check'||action==='daily')paint();}
    finally{busy=false;contents.inert=false;}
}
document.addEventListener('click',e=>{
    const button=e.target.closest('button');if(!button)return;
    if(button.dataset.panel)openPanel(button.dataset.panel);
    else if(button.hasAttribute('data-weather'))save('mood',{weather:button.dataset.weather});
    else if(button.dataset.diaryTab){diaryTab=button.dataset.diaryTab;paint();}
    else if(button.dataset.forget)save('forget',{id:Number(button.dataset.forget)});
    else if(button.hasAttribute('data-reflect'))save('reflect',{});
    else if(button.id==='sync-models')syncModels();
    else if(button.id==='import-role')$('#role-file').click();
    else if(button.id==='export-role'){
        const c={...(roleDraft||state.role),...Object.fromEntries(new FormData(button.form))};
        const url=URL.createObjectURL(new Blob([JSON.stringify(toV2Card(c),null,2)],{type:'application/json'}));
        const a=document.createElement('a');a.href=url;a.download=(c.name||'大肥鱼')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }
    else if(button.hasAttribute('data-make'))save('story',{});
});
sheet.addEventListener('submit',e=>{
    e.preventDefault();const form=e.target;const data=new FormData(form);
    const payload=Object.fromEntries(data);
    if(form.dataset.action==='role')save('role',{card:{...(roleDraft||state.role),...payload}});
    else save(form.dataset.action,{...payload,search:data.has('search')});
});
sheet.addEventListener('change',async e=>{
    if(e.target.id==='providers'){providerDraft=e.target.value;paint();}
    if(e.target.id==='pick-model'){$('#model-id').value=e.target.value;if(!e.target.value)$('#model-id').focus();}
    if(e.target.id==='role-library'){roleDraft=state.roles.find(c=>c.id===e.target.value)||{};paint();}
    if(e.target.id==='role-file'&&e.target.files.length){
        try{roleDraft=fromV2Card(JSON.parse(await e.target.files[0].text()),{roles:state.roles});paint();notice.textContent='已读入角色卡，保存后生效。';}
        catch{notice.textContent='无法读取角色卡，请选择有效的角色卡 JSON。';}
    }
    if(e.target.matches('[data-id]'))save('check',{id:Number(e.target.dataset.id),done:e.target.checked});
    if(e.target.matches('[data-daily]'))save('daily',{enabled:e.target.checked});
});
async function syncModels(){
    const id=providerDraft||state.provider;
    notice.textContent='正在读取模型…';
    try{
        const res=await fetch('/api/models/'+id),data=await res.json();
        if(!res.ok)throw Error(data.error);
        catalogs[id]=data.models;
        if(panel==='provider'&&id===(providerDraft||state.provider)){paint();notice.textContent='账户返回了 '+data.models.length+' 个候选模型。';}
    }catch(e){notice.textContent=e.message;}
}
window.addEventListener('fish-life-change',async()=>{
    await refresh();
    if(sheet.open&&!busy&&(panel==='mind'||(panel==='diary'&&diaryTab==='fish'))&&!contents.contains(document.activeElement))paint();
});
window.addEventListener('fish-panel',e=>openPanel(e.detail));
$('#closePanel').onclick=()=>sheet.close();
sheet.addEventListener('click',e=>{if(e.target===sheet){const r=sheet.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)sheet.close();}});
