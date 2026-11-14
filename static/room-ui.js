import {toV2Card,fromV2Card} from './vendor/cosplay-store.js';
const $=s=>document.querySelector(s);
const sheet=$('#sheet'), contents=$('#contents'), notice=$('#notice');
const titles={diary:'日记本',mood:'心情天气',todo:'待办便签',story:'每日小故事',chat:'和大肥鱼聊聊',provider:'模型设置',role:'角色卡',memory:'记忆簿',mind:'她的心愿'};
titles.collection='我的收藏';
let state, panel, busy=false, diaryTab='fish',roleDraft,providerDraft;
const catalogs={};
const html=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function entries(rows, key='body'){
    return rows.map(row=>'<article class="entry"><small>'+html(row.day)+(row.model?' · '+html(row.model):'')+'</small>'+html(row[key])+'</article>').join('');
}
function chatMessage(message){
    const mine=message.role==='user';
    let sticker='';
    if(message.sticker?.startsWith('collection/')){
        const name=message.sticker.slice(11),url='/api/collection/'+encodeURIComponent(name);
        sticker=name.endsWith('.mp4')?'<video controls playsinline class="chat-sticker" src="'+url+'"></video>':'<img class="chat-sticker" alt="收藏图片" src="'+url+'">';
    }else if(message.sticker){
        sticker='<img class="chat-sticker" alt="大肥鱼表情" src="/api/stickers/'+message.sticker.split('/').map(encodeURIComponent).join('/')+'">';
    }
    const sources=(message.sources||[]).map((s,i)=>'<a href="'+html(s.url)+'" target="_blank" rel="noopener noreferrer">'+(i+1)+'. '+html(s.title)+'</a>').join('');
    return '<article class="chat-line '+(mine?'outgoing':'incoming')+'" aria-label="'+(mine?'我':'大肥鱼')+'">'+
        (mine?'':'<span class="portrait chat-avatar" aria-hidden="true"></span>')+
        '<div class="chat-bubble">'+html(message.body)+sticker+(sources?'<div class="chat-sources">'+sources+'</div>':'')+'</div></article>';
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
        const options=[...new Set([p.model,...(catalogs[id]|| (id==='openai'?['gpt-4.1-mini','gpt-4.1','gpt-4o-mini']:[]))])];
        contents.innerHTML='<form data-action="provider"><label>服务商<select id="providers" name="provider">'+Object.entries(state.providers).map(([k,v])=>'<option value="'+k+'" '+(k===id?'selected':'')+'>'+html(v.name)+(v.ready?'':' · 待配置密钥')+'</option>').join('')+'</select></label><label>选择模型<select id="pick-model">'+options.map(m=>'<option>'+html(m)+'</option>').join('')+'<option value="">输入其他模型 ID…</option></select></label><label>模型 ID<input name="model" id="model-id" required maxlength="150" value="'+html(p.model)+'"></label><div class="row"><button type="button" id="sync-models" '+(p.ready?'':'disabled')+'>读取账户模型</button><button class="primary" '+(p.ready?'':'disabled')+'>保存选择</button></div><small>当前使用 '+html(state.providers[state.provider].model)+'</small></form>';
        const destinations=[['private','私聊',[['room','小窝聊天'],...(state.wechatOwner?[['wechat','微信私聊']]:[]),['off','关闭']]]];
        if('group' in state.proactive)destinations.push(['group','微信群冷场后主动开场',[['off','关闭'],['wechat','开启']]]);
        contents.insertAdjacentHTML('beforeend','<section class="panelbody"><h3>定时主动聊天</h3>'+destinations.map(([target,label,options])=>'<label>'+label+'<select data-proactive="'+target+'">'+options.map(([v,n])=>'<option value="'+v+'" '+(state.proactive[target]===v?'selected':'')+'>'+n+'</option>').join('')+'</select></label>').join('')+'<small>间隔 2–6 小时，上海时间 23:00–09:00 免打扰。连续两次无人回应后暂停。</small></section>');
        if(state.wechatOwner){
            contents.insertAdjacentHTML('beforeend',`
                <form data-action="private-voice">
                    <h3>微信私聊语音</h3>
                    <label>语音概率（%）<input type="number" name="probability" min="0" max="100" step="1" required value="${state.privateVoiceProbability}"></label>
                    <small>每次私聊回复或定时问候，都按这个概率发语音。设为 0% 时，仍可说“用语音回复”。</small>
                    <button class="primary">保存语音概率</button>
                </form>`);
        }
        if(state.groupInterjection){
            const {enabled,probability,per_minute}=state.groupInterjection;
            contents.insertAdjacentHTML('beforeend',`
                <form data-action="group-interjection">
                    <h3>微信群即时插话</h3>
                    <label><span><input type="checkbox" name="enabled" ${enabled?'checked':''}> 允许大肥鱼在群友聊天时插话</span></label>
                    <label>触发概率（%）<input type="number" name="probability" min="0" max="100" step="1" required value="${probability}"></label>
                    <label>每分钟最多发送（条）<input type="number" name="per_minute" min="1" max="10" step="1" required value="${per_minute}"></label>
                    <small>对普通群消息按概率接话，两次触发至少间隔 10 秒。点名回复不占额度。</small>
                    <button class="primary">保存插话设置</button>
                </form>`);
        }
        contents.insertAdjacentHTML('beforeend','<small>表情作者 <a href="https://space.bilibili.com/103739" target="_blank" rel="noopener">可以叫我云大人／雾雪</a> · <a href="https://kiriyuki.com" target="_blank" rel="noopener">kiriyuki.com</a></small>');
    }else if(panel==='role'){
        const c=roleDraft||state.role;
        contents.innerHTML='<form data-action="role"><label>角色库<select id="role-library">'+state.roles.map(r=>'<option value="'+html(r.id)+'" '+(r.id===c.id?'selected':'')+'>'+html(r.name)+'</option>').join('')+'<option value="" '+(!c.id?'selected':'')+'>新建角色卡…</option></select></label>'+[['name','名字'],['description','身份'],['personality','性格'],['style','说话习惯'],['behavior','爱好与习惯']].map(([k,n])=>'<label>'+n+(k==='name'?'<input required maxlength="100" name="name" value="'+html(c.name||'')+'">':'<textarea rows="2" maxlength="4000" name="'+k+'">'+html(c[k]||'')+'</textarea>')+'</label>').join('')+'<div class="row"><button class="primary">保存并使用</button><button type="button" id="import-role">导入 JSON</button><button type="button" id="export-role">导出 JSON</button></div><input type="file" accept=".json,application/json" id="role-file" hidden></form>';
        const ruleBox=document.createElement('label');
        ruleBox.textContent='聊天表达规则';
        const rules=document.createElement('textarea');
        rules.name='rules';rules.rows=5;rules.maxLength=4000;rules.value=c.rules||'';
        ruleBox.append(rules);
        contents.querySelector('form .row').before(ruleBox);
    }else if(panel==='memory'){
        contents.innerHTML='<form data-action="memory"><label>关于谁或哪里<input name="entity" maxlength="80" required value="来访者"></label><label>想记住的事<input name="body" maxlength="700" required></label><button class="primary">记下来</button></form><div class="history">'+state.memories.map(m=>'<article class="entry"><small>'+html(m.entity)+' · '+html(m.source)+' · '+html(m.day)+'</small>'+html(m.body)+'<button class="quiet" data-forget="'+m.id+'">忘掉</button></article>').join('')+'</div><a class="export" href="/api/memory/graph" download="大肥鱼-记忆图谱.json">导出记忆图谱</a>';
    }else if(panel==='mind'){
        const labels={active:'正在做',queued:'接下来',wish:'想扩展',done:'已完成'};
        contents.innerHTML='<div class="mind-list">'+[...state.thoughts,...state.recent].map(g=>'<article class="entry"><small>'+labels[g.state]+' · '+html(g.source)+'</small><b>'+html(g.title)+'</b><p>'+html(g.result||g.reason)+'</p></article>').join('')+'</div><form data-action="wish"><label>给未来的小窝留个想法<input name="body" maxlength="180" required></label><button>收进愿望簿</button></form><button class="primary reflect" data-reflect>用 '+html(state.providers[state.provider].model)+' 构思一次</button><small>手动调用一次模型，写一页日记、一件待办和一个新愿望。</small>';
    }else if(panel==='collection'){
        contents.innerHTML='<form data-upload><label>添加图片、表情或短视频<input type="file" required name="asset" accept="image/png,image/jpeg,image/webp,image/gif,video/mp4"></label><label>素材描述<input name="description" maxlength="240" placeholder="例如：大肥鱼点头，表示同意"></label><button class="primary">收藏</button></form><div class="asset-grid">'+state.collection.map(item=>{
            const url='/api/collection/'+encodeURIComponent(item.name);
            const preview=item.name.endsWith('.mp4')?'<video controls playsinline preload="metadata" src="'+url+'"></video>':'<a href="'+url+'" target="_blank" rel="noopener"><img loading="lazy" src="'+url+'" alt="'+html(item.description||'收藏图片')+'"></a>';
            return '<article>'+preview+'<details><summary>'+html(item.description||'添加素材描述')+'</summary><form data-action="collection-label"><input type="hidden" name="name" value="'+html(item.name)+'"><label>素材描述<textarea required name="description" maxlength="240">'+html(item.description||'')+'</textarea></label><div class="row"><button>保存描述</button><button type="button" data-inspect="'+html(item.name)+'">用模型识图</button></div></form></details></article>';
        }).join('')+'</div>';
    }else if(panel==='chat'){
        contents.innerHTML='<div class="chat-log" role="log" aria-label="聊天记录">'+(state.chat.map(chatMessage).join('')||'<p class="chat-empty">和大肥鱼打个招呼吧</p>')+'</div><form data-action="chat" class="chat-compose"><textarea aria-label="消息" name="body" rows="2" required maxlength="2000" placeholder="发消息…"></textarea><div class="chat-controls"><label><input type="checkbox" name="search">'+(state.provider==='openai'?'联网搜索':'查维基百科')+'</label><button class="primary">发送</button></div></form>';
        const log=contents.querySelector('.chat-log');log.dataset.latest=state.chat.at(-1)?.id||0;
        contents.querySelector('.chat-controls .primary').insertAdjacentHTML('beforebegin','<button type="button" id="attach-media">附件</button><input hidden type="file" name="mediaFile" accept="image/png,image/jpeg,image/webp,image/gif,video/mp4"><button type="button" data-panel="collection">收藏库</button>');
        requestAnimationFrame(()=>{log.scrollTop=log.scrollHeight;});
    }
    contents.inert=busy;
}
let ready=refresh().catch(e=>{$('#day').textContent=e.message;});
async function openPanel(key){
    if(!titles[key]||busy)return;
    await ready;
    if(!state||key==='chat')await refresh();
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
    else if(button.id==='attach-media')button.form.elements.mediaFile.click();
    else if(button.hasAttribute('data-weather'))save('mood',{weather:button.dataset.weather});
    else if(button.dataset.diaryTab){diaryTab=button.dataset.diaryTab;paint();}
    else if(button.dataset.forget)save('forget',{id:Number(button.dataset.forget)});
    else if(button.dataset.inspect)save('collection-inspect',{name:button.dataset.inspect});
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
sheet.addEventListener('submit',async e=>{
    e.preventDefault();const form=e.target;const data=new FormData(form);
    const payload=Object.fromEntries(data);
    if(form.dataset.action==='chat'){
        const file=payload.mediaFile;
        delete payload.mediaFile;
        if(file?.size){
            if(file.size>20*1024*1024){notice.textContent='单个素材最多 20 MiB。';return;}
            busy=true;contents.inert=true;notice.textContent='正在收藏附件…';
            try{
                const res=await fetch('/api/collection/upload',{method:'POST',body:file});
                const result=await res.json();
                if(!res.ok)throw new Error(result.error||'附件上传失败');
                payload.attachment=result.name;
            }catch(err){notice.textContent=err.message;return;}
            finally{busy=false;contents.inert=false;}
        }
    }
    if(form.hasAttribute('data-upload')){
        if(payload.asset.size>20*1024*1024){notice.textContent='单个素材最多 20 MiB。';return;}
        busy=true;contents.inert=true;notice.textContent='正在收藏…';
        try{
            const res=await fetch('/api/collection/upload?description='+encodeURIComponent(payload.description),{method:'POST',body:payload.asset});
            if(!res.ok)throw new Error((await res.json()).error||'收藏失败');
            await refresh();paint();notice.textContent='已收藏。';
        }catch(err){notice.textContent=err.message;}
        finally{busy=false;contents.inert=false;}
        return;
    }
    if(form.dataset.action==='group-interjection')save('group-interjection',{enabled:data.has('enabled'),probability:Number(payload.probability),per_minute:Number(payload.per_minute)});
    else if(form.dataset.action==='private-voice')save('private-voice',{probability:Number(payload.probability)});
    else if(form.dataset.action==='role')save('role',{card:{...(roleDraft||state.role),...payload}});
    else save(form.dataset.action,{...payload,search:data.has('search')});
});
sheet.addEventListener('change',async e=>{
    if(e.target.name==='mediaFile'){
        const file=e.target.files[0];
        e.target.form.elements.body.required=!file;
        notice.textContent=file?'待发送：'+file.name:'';
    }
    if(e.target.id==='providers'){providerDraft=e.target.value;paint();}
    if(e.target.id==='pick-model'){$('#model-id').value=e.target.value;if(!e.target.value)$('#model-id').focus();}
    if(e.target.id==='role-library'){roleDraft=state.roles.find(c=>c.id===e.target.value)||{};paint();}
    if(e.target.id==='role-file'&&e.target.files.length){
        try{roleDraft=fromV2Card(JSON.parse(await e.target.files[0].text()),{roles:state.roles});paint();notice.textContent='已读入角色卡，保存后生效。';}
        catch{notice.textContent='无法读取角色卡，请选择有效的角色卡 JSON。';}
    }
    if(e.target.matches('[data-id]'))save('check',{id:Number(e.target.dataset.id),done:e.target.checked});
    if(e.target.matches('[data-daily]'))save('daily',{enabled:e.target.checked});
    if(e.target.matches('[data-proactive]'))save('proactive',{target:e.target.dataset.proactive,mode:e.target.value});
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
setInterval(async()=>{
    if(!sheet.open||panel!=='chat'||busy||document.hidden)return;
    const log=contents.querySelector('.chat-log');
    const last=Number(log?.dataset.latest||0);
    const res=await fetch('/api/chat/since/'+last,{cache:'no-store'}).catch(()=>null);
    if(!res?.ok)return;
    const rows=await res.json();
    if(!log.isConnected||busy||!rows.length)return;
    const atEnd=log.scrollTop+log.clientHeight>=log.scrollHeight-10;
    log.querySelector('.chat-empty')?.remove();
    log.insertAdjacentHTML('beforeend',rows.map(chatMessage).join(''));
    log.dataset.latest=rows.at(-1).id;
    if(atEnd)log.scrollTop=log.scrollHeight;
},15000);
$('#closePanel').onclick=()=>sheet.close();
sheet.addEventListener('click',e=>{if(e.target===sheet){const r=sheet.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)sheet.close();}});
