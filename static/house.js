import * as THREE from './vendor/three.module.js';
import { createWorld } from './world.js';
import { makeCompanion } from './companions.js';
import { buildStreet } from './neighborhood.js';
import { Routine } from './routine.js';
import { createGardenWorld } from './garden-world.js';
import { createGarden, gardenView, applyGardenAction, CROPS } from './garden-state.js';

const stage = document.querySelector('#stage');
const canvas = document.querySelector('#scene');
const load = document.querySelector('#load');
const renderer = new THREE.WebGLRenderer({ canvas, antialias:true, powerPreference:'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.8));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.shadowMap.autoUpdate = false;
renderer.shadowMap.needsUpdate = true;
const world = createWorld(renderer, {quality:'balanced'});
world.setCeilingVisible(false);
world.setLabelsVisible(false);
world.updateEnvironment({hour:14, lamp:true, kind:'desk'});
world.scene.add(new THREE.AmbientLight(0xfff5e5, .48));
const camera = new THREE.PerspectiveCamera(49, 1, .045, 110);
const target = new THREE.Vector3();
let yaw, pitch, radius, view, marksOn = true;
const views = {
    follow:{target:[10.08,.76,2.50],offset:[.76,.22,1.37]},
    desk:{target:[9.73,.93,2.34], offset:[1.29,1.04,1.92], name:'卧室 · 书桌旁'},
    living:{target:[6.3,.93,2.90], offset:[-2.6,1.8,3.2], name:'客厅 · 沙发旁'},
    garden:{target:[6,.45,-3.65],offset:[-3.7,6.0,-8.2]},
    street:{target:[-6.42,1.0,.64],offset:[5.72,2.04,.62]},
    all:{target:[1.3,.50,.60],offset:[-13,17,17]}
};
function setView(key){
    view = key;
    camera.fov=key==='street'?66:49;camera.updateProjectionMatrix();
    const preset = views[key];
    target.fromArray(preset.target);
    const offset = new THREE.Vector3(...preset.offset);
    radius = offset.length() * (stage.clientWidth < 600 ? 1.12 : 1);
    yaw = Math.atan2(offset.x,offset.z);
    pitch = Math.asin(offset.y/offset.length());
    stage.dataset.view=key;
    document.querySelector('#invite').hidden=!['desk','living','garden','street'].includes(key);
    document.querySelector('#garden-entry').hidden=key!=='garden';
    document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed', b.dataset.view===key));
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
setView('follow');
const point = (x,y,z)=>new THREE.Vector3(x,y,z);
const pickables = [];
function piece(shape, color, pos, action){
    const object = new THREE.Mesh(shape, new THREE.MeshStandardMaterial({color, roughness:.75}));
    object.position.copy(pos); object.userData.action=action;
    world.scene.add(object); pickables.push(object);
    return object;
}
const book=new THREE.Group();book.position.set(8.84,.805,2.94);book.rotation.y=.13;world.scene.add(book);
const paper=new THREE.MeshStandardMaterial({color:0xf6edd5,roughness:.93});
const leather=new THREE.MeshStandardMaterial({color:0x456c68,roughness:.76});
for(const sign of [-1,1]){
    const page=new THREE.Mesh(new THREE.BoxGeometry(.164,.021,.234),paper);
    page.rotation.z=sign*.065;page.position.set(sign*.084,.013,0);book.add(page);
    const cover=new THREE.Mesh(new THREE.BoxGeometry(.172,.008,.246),leather);
    cover.position.set(sign*.084,-.004,0);book.add(cover);
    for(let i=0;i<6;i++){
        const line=new THREE.Mesh(new THREE.BoxGeometry(.096-(i%3)*.011,.0014,.0024),world.mats.walnut);
        line.position.set(sign*.080,.025+(sign*.080-sign*.084)*sign*.065,-.076+i*.025);book.add(line);
    }
}
const ribbon=new THREE.Mesh(new THREE.BoxGeometry(.014,.003,.098),world.mats.terracotta);
ribbon.position.set(.006,.021,.099);book.add(ribbon);
book.traverse(m=>{if(m.isMesh){m.userData.action='diary';pickables.push(m);}});
const board = world.memoryMesh;
board.position.x=8.537;
piece(new THREE.BoxGeometry(.036,.69,.91),0x77573e,point(8.51,1.45,3.85),'todo');
for(const dz of [-.2,.2])piece(new THREE.SphereGeometry(.022,14,10),0xb48b52,point(8.552,1.66,3.85+dz),'todo');
board.userData.action='todo'; pickables.push(board);
piece(new THREE.BoxGeometry(.25,.07,.53),0xb98c65,point(12.96,.81,2.52),'mood');
const bottle = piece(new THREE.SphereGeometry(.125,20,16),0x84cfc9,point(12.94,.97,2.52),'mood');
bottle.scale.y=1.18;
const weatherColors={'晴天':0xffc563,'微风':0x80d1bb,'多云':0xb9c2d0,'小雨':0x7faadd,'雷阵雨':0x8283ae};
window.addEventListener('fish-state',({detail})=>{
    const todo=detail.todos.filter(t=>!t.done).slice(0,4).map(t=>t.body);
    world.setMemoryNotes(todo.length?todo:['写张新便签']);
    const weather=detail.moods.find(m=>m.day===detail.day)?.weather;
    bottle.material.color.setHex(weatherColors[weather]??0x84cfc9);
});
piece(new THREE.CylinderGeometry(.045,.052,.09,14),0xa9ded6,point(12.94,1.13,2.52),'mood');
piece(new THREE.CylinderGeometry(.044,.048,.033,14),0xa78059,point(12.94,1.19,2.52),'mood');
const pages = piece(new THREE.BoxGeometry(.27,.045,.30),0x526b95,point(10.10,.55,.55),'story');
pages.rotation.y=-.15;
const street=buildStreet(world.scene);
const garden=createGardenWorld(world,renderer,{quality:'balanced'});
const gardenKey='dafeiyu.garden.v1';
const saved=localStorage.getItem(gardenKey);
let beds=saved?JSON.parse(saved):createGarden();
garden.update(gardenView(beds));
localStorage.setItem(gardenKey,JSON.stringify(beds));
const plotPanel=document.querySelector('#plot-panel');
const plotButtons=document.querySelector('#plots');
const gardenActions=document.querySelector('#garden-actions');
let selectedPlot=0;
function showPlot(id){
    selectedPlot=id;
    const state=gardenView(beds),plot=state.plots[id],crop=CROPS.find(c=>c.id===plot.cropId);
    garden.setSelected(id);
    document.querySelector('#plot-title').textContent=(id+1)+' 号菜畦';
    plotButtons.innerHTML=state.plots.map(p=>'<button data-plot="'+p.id+'" aria-pressed="'+(p.id===id)+'">'+(p.id+1)+'</button>').join('');
    const status=plot.mature?'可以采收':plot.needsWater?'需要浇水':Math.round(plot.progress*100)+'%';
    const seedChoices=CROPS.map(c=>'<option value="'+c.id+'">'+c.name+' · '+state.seeds[c.id]+' 粒</option>').join('');
    gardenActions.innerHTML=crop?'<h3>'+crop.name+' · '+status+'</h3><button data-care="'+(plot.mature?'harvest':'water')+'">'+(plot.mature?'采收':'浇水')+'</button>':
        plot.tilled?'<label>种子<select id="seeds">'+seedChoices+'</select></label><button data-care="plant">播种</button>':'<button data-care="till">松土</button>';
    if(!plotPanel.open)plotPanel.showModal();
}
function tend(action){
    const result=applyGardenAction(beds,action);beds=result.state;
    localStorage.setItem(gardenKey,JSON.stringify(beds));garden.update(gardenView(beds));
    if(plotPanel.open){showPlot(selectedPlot);document.querySelector('#plot-result').textContent=result.message;}
    return result.message;
}
plotButtons.onclick=e=>{if(e.target.dataset.plot!==undefined){document.querySelector('#plot-result').textContent='';showPlot(Number(e.target.dataset.plot));}};
gardenActions.onclick=e=>{if(e.target.dataset.care)tend({type:e.target.dataset.care,plotId:selectedPlot,cropId:document.querySelector('#seeds')?.value});};
document.querySelector('#plot-close').onclick=()=>plotPanel.close();
plotPanel.onclose=()=>{garden.setSelected(-1);document.querySelector('#plot-result').textContent='';};
document.querySelector('#garden-entry').onclick=()=>showPlot(selectedPlot);
const routine=new Routine(()=>{
    const state=gardenView(beds),plots=state.plots;
    const plot=plots.find(p=>p.cropId&&!p.mature&&p.moisture<.8)??plots.find(p=>p.mature)??plots.find(p=>!p.cropId)??plots[0];
    let kind=plot.mature?'harvest':plot.cropId?'water':plot.tilled?'plant':'till';
    const seed=CROPS.find(c=>state.seeds[c.id]>0);
    if(kind==='plant'&&!seed)kind='watch';
    return {plotId:plot.id,cropId:seed?.id,kind,label:'在菜园'+({water:'浇水',harvest:'采收',till:'松土',plant:'播种',watch:'看菜苗'})[kind]};
},job=>job.kind==='watch'?'看了看菜苗。':tend({type:job.kind,plotId:job.plotId,cropId:job.cropId}),async(goal,outcome)=>{
    async function send(action,body){
        const res=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        if(!res.ok)throw Error('生活记录暂时无法同步。');return res.json();
    }
    if(goal)await send('complete',{id:goal.id,result:outcome});
    const plots=gardenView(beds).plots;
    const result=await send('decide',{garden:plots.some(p=>p.mature||p.needsWater)});
    window.dispatchEvent(new Event('fish-life-change'));
    return result.goal;
});
document.querySelector('#invite').onclick=()=>routine.go(view);
const pet=new THREE.Group();world.scene.add(pet);
const figures={A:makeCompanion('A'),B:makeCompanion('B')};
pet.add(figures.A.root,figures.B.root);
await Promise.all(Object.values(figures).map(figure=>figure.ready)).catch(error=>{
    load.textContent='角色资源加载失败，请刷新重试。';
    throw error;
});
const selector=document.querySelector('#costume');
let active;
function costume(key){
    active=figures[key];for(const figure of Object.values(figures))figure.root.visible=figure===active;
    selector.value=key;document.body.dataset.actor=key;
}
costume(localStorage.getItem('dafeiyu.costume')==='B'?'B':'A');
selector.onchange=()=>{costume(selector.value);localStorage.setItem('dafeiyu.costume',selector.value);};
// Click volume covers the articulated body in both outfits and follows it around the neighbourhood.
const petHit=new THREE.Mesh(new THREE.CapsuleGeometry(.28,.78,5,12),new THREE.MeshBasicMaterial({visible:false}));
petHit.position.y=.71;petHit.userData.action='chat';pet.add(petHit);pickables.push(petHit);
const shadow=new THREE.Mesh(new THREE.CircleGeometry(1,40),new THREE.MeshBasicMaterial({color:0x47394a,opacity:.17,transparent:true,depthWrite:false}));
shadow.rotation.x=-Math.PI/2;shadow.scale.set(.27,.20,1);world.scene.add(shadow);
const ball=new THREE.Mesh(new THREE.IcosahedronGeometry(.12,1),new THREE.MeshStandardMaterial({color:0xe6ac64,roughness:.6,flatShading:true}));
const stripe=new THREE.Mesh(new THREE.TorusGeometry(.116,.012,6,24),new THREE.MeshStandardMaterial({color:0x7eacc2}));
ball.add(stripe);pet.add(ball);
const openBook=new THREE.Group();pet.add(openBook);
for(const s of [-1,1]){
    const page=new THREE.Mesh(new THREE.BoxGeometry(.122,.025,.166),new THREE.MeshStandardMaterial({color:0xf9eacb}));
    page.position.x=s*.056;page.rotation.z=s*.13;openBook.add(page);
}
openBook.position.set(0,.56,.21);openBook.rotation.x=.35;
const rightPalm=new THREE.Vector3(),leftPalm=new THREE.Vector3();
const markers=[
    ['diary','日记本',point(8.80,.91,2.94)],['todo','待办板',point(8.55,1.75,3.58)],
    ['mood','天气瓶',point(12.94,1.35,2.52)],['chat','大肥鱼',point(10.12,1.43,2.43)],
    ['story','故事书',point(10.10,.70,.55)]
].map(([action,name,pos])=>{
    const button=document.createElement('button'); button.className='pin';button.textContent=name;
    button.dataset.panel=action; document.querySelector('#marks').append(button); return {pos,button};
});
document.querySelector('#labels').onclick=e=>{
    marksOn=!marksOn;e.currentTarget.textContent='物件标记　'+(marksOn?'开':'关');
    e.currentTarget.setAttribute('aria-pressed',marksOn);
};
let down=null;
canvas.onpointerdown=e=>{down={x:e.clientX,y:e.clientY,yaw,pitch,moved:false};canvas.setPointerCapture(e.pointerId)};
canvas.onpointermove=e=>{
    if(!down)return;
    const dx=e.clientX-down.x,dy=e.clientY-down.y;
    if(Math.hypot(dx,dy)>4)down.moved=true;
    if(down.moved){yaw=down.yaw-dx*.007;pitch=THREE.MathUtils.clamp(down.pitch+dy*.006,.06,1.48);}
};
const ray = new THREE.Raycaster();
canvas.onpointerup=e=>{
    if(down&&!down.moved){
        const rect=canvas.getBoundingClientRect();
        ray.setFromCamera(new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,1-(e.clientY-rect.top)/rect.height*2),camera);
        const hit=ray.intersectObjects(view==='garden'?[...pickables,...garden.pickables]:pickables,false)[0];
        if(hit?.object.userData.gardenPlot!==undefined)showPlot(hit.object.userData.gardenPlot);
        else if(hit)window.dispatchEvent(new CustomEvent('fish-panel',{detail:hit.object.userData.action}));
    }
    down=null;
};
canvas.onpointercancel=()=>down=null;
canvas.addEventListener('wheel',e=>{e.preventDefault();radius=THREE.MathUtils.clamp(radius*Math.exp(e.deltaY*.001),1.5,26)},{passive:false});
canvas.ondblclick=()=>setView(view);
new ResizeObserver(()=>{
    renderer.setSize(stage.clientWidth,stage.clientHeight,false);
    camera.aspect=stage.clientWidth/stage.clientHeight;camera.updateProjectionMatrix();
}).observe(stage);
const projected = new THREE.Vector3();
// Keep the follow camera on the character's side of tall furniture, lintels and walls.
world.root.updateMatrixWorld(true);
const blockers=[];
world.root.traverse(o=>{
    if(!o.isMesh||!o.visible||!o.material?.visible||o.material.transparent)return;
    o.geometry.computeBoundingBox();
    const box=o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld),size=box.getSize(new THREE.Vector3());
    if(size.y>.04&&box.max.y>.46&&box.min.y<2.8&&size.x*size.z>.008)blockers.push(box.expandByScalar(.065));
});
const sight=new THREE.Ray(),hitPoint=new THREE.Vector3(),arm=new THREE.Vector3();
function clearRadius(angle,elevation){
    arm.set(Math.sin(angle)*Math.cos(elevation),Math.sin(elevation),Math.cos(angle)*Math.cos(elevation));
    sight.set(target,arm);
    let clear=radius;
    for(const box of blockers){
        if(sight.intersectBox(box,hitPoint))clear=Math.min(clear,Math.max(.22,hitPoint.distanceTo(target)-.14));
    }
    return clear;
}
let lastTime=0, elapsed=0, gardenTick=0;
renderer.setAnimationLoop(time=>{
    if(document.hidden){lastTime=0;return;}
    const dt=lastTime?Math.min((time-lastTime)/1000,.65):0;
    lastTime=time;elapsed+=dt;
    routine.update(dt);
    pet.position.set(routine.x,0,routine.z);pet.rotation.y=routine.yaw;
    active.animate(elapsed,routine.kind);
    ball.visible=routine.kind==='play';
    openBook.visible=routine.kind==='read';
    if(ball.visible||openBook.visible){
        for(const [joint,point] of [[active.joints.handR,rightPalm],[active.joints.handL,leftPalm]]){
            point.set(0,-.027,.015);
            pet.worldToLocal(joint.localToWorld(point));
        }
        if(ball.visible){
            const phase=(1+Math.sin(elapsed*3.5))*.5;
            ball.position.lerpVectors(rightPalm,leftPalm,phase);
            ball.position.y+=.105+phase*(1-phase)*1.10;
            ball.rotation.z=elapsed*2;
        }else{
            openBook.position.lerpVectors(rightPalm,leftPalm,.5);
            openBook.position.y+=.014;
            openBook.scale.x=rightPalm.distanceTo(leftPalm)/.236;
        }
    }
    shadow.position.set(routine.x,.069,routine.z);
    if(view==='follow')target.set(routine.x,.74,routine.z);
    const tending=routine.place==='garden'&&['till','plant','harvest','water'].includes(routine.kind);
    if(tending)active.joints.handR.localToWorld(rightPalm.set(0,-.027,.015));
    garden.updateCharacter(tending?{kind:'garden_'+routine.kind,gardenWork:{type:routine.kind,phase:'working'}}:null,rightPalm,Math.PI-routine.yaw);
    if(tending)garden.animateCharacter(time);
    if(elapsed-gardenTick>=10){gardenTick=elapsed;garden.update(gardenView(beds));}
    const indoors=view==='desk'||view==='living'||(view==='follow'&&routine.x>0&&routine.z>0);
    street.visible=!indoors;garden.group.visible=!indoors;
    if(stage.dataset.activity!==routine.label){
        stage.dataset.activity=routine.label;document.querySelector('#place').textContent=routine.label;
        world.setScreenState('desk',routine.kind==='write');
    }
    let distance=radius,azimuth=yaw,elevation=pitch;
    if(indoors&&view!=='all'){
        distance=clearRadius(yaw,pitch);
        if(distance<Math.min(1.45,radius*.72)){
            for(const delta of [.68,-.68,1.35,-1.35,Math.PI]){
                const candidate=clearRadius(yaw+delta,pitch+.12);
                if(candidate>distance){distance=candidate;azimuth=yaw+delta;elevation=pitch+.12;}
                if(distance>=Math.min(radius-.05,1.9))break;
            }
        }
    }
    if(view==='follow'){
        // Keep the full silhouette in frame even when a cabinet shortens the camera boom.
        const fov=THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(2*Math.atan(1.00/Math.max(.60,distance-.34))),49,90);
        if(Math.abs(camera.fov-fov)>.08){camera.fov=fov;camera.updateProjectionMatrix();}
    }
    camera.position.set(target.x+Math.sin(azimuth)*Math.cos(elevation)*distance,target.y+Math.sin(elevation)*distance,target.z+Math.cos(azimuth)*Math.cos(elevation)*distance);
    camera.lookAt(target);camera.updateMatrixWorld();
    world.updateCutaway(camera.position,target,true);
    for(const {pos,button} of markers){
        if(button.dataset.panel==='chat')pos.set(routine.x,1.52,routine.z);
        projected.copy(pos).project(camera);
        const x=(projected.x+1)*.5, y=(1-projected.y)*.5;
        button.hidden=!marksOn||!['desk','follow'].includes(view)||pos.distanceTo(target)>4||projected.z>1||projected.z< -1||x<.04||x>.96||y<.09||y>.94;
        if(!button.hidden){button.style.left=x*100+'%';button.style.top=y*100+'%';}
    }
    renderer.render(world.scene,camera);load.hidden=true;document.body.dataset.rendered='true';
});
