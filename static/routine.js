// Neighbouring waypoints follow the apartment doorways, the garden aisle and the crosswalk.
const points={
    home:[9.99,2.85], desk:[9.93,2.98], aisle:[10,3.74], bedroomDoor:[9.15,4.04],
    hall:[9.15,4.98], hallEnd:[7.85,4.98], living:[7.84,4.24],
    south:[7.85,6.38], entryLane:[3.67,6.38], mat:[.78,6.25], gate:[-.65,6.25],
    gardenGate:[-.65,-3.60], gardenAisle:[.72,-3.60], bed0:[2,-3.60],
    bed1:[4.7,-3.60], bed2:[7.4,-3.60], bed3:[10.1,-3.60],
    crossing:[-2.5,6.25], bakery:[-5.81,6.25], flowers:[-5.69,.4], books:[-5.69,-4.05]
};
const paths=[
    ['home','desk'],['home','aisle','bedroomDoor','hall','hallEnd','south','entryLane','mat','gate'],
    ['hallEnd','living'],['gate','gardenGate','gardenAisle','bed0','bed1','bed2','bed3'],
    ['gate','crossing','bakery','flowers','books']
];
const links=Object.fromEntries(Object.keys(points).map(key=>[key,[]]));
for(const path of paths)for(let i=1;i<path.length;i++){links[path[i-1]].push(path[i]);links[path[i]].push(path[i-1]);}
function route(from,to){
    const queue=[[from]],seen=new Set([from]);
    for(const visited of queue){
        const last=visited[visited.length-1];
        if(last===to)return visited.slice(1);
        for(const next of links[last])if(!seen.has(next)){seen.add(next);queue.push([...visited,next]);}
    }
}
const destinations={
    desk:{node:'desk',kind:'write',label:'在书桌前写字',angle:-1.86,dwell:9},
    living:{node:'living',kind:'play',label:'在客厅抛接彩球',angle:-.25,dwell:9},
    garden:{node:'bed1',kind:'water',label:'在菜园浇水',angle:0,dwell:7},
    street:{node:'flowers',kind:'watch',label:'在花店看花',angle:-Math.PI/2,dwell:8},
    bookshop:{node:'books',kind:'read',label:'在街边翻书',angle:-Math.PI/2,dwell:9},
    home:{node:'home',kind:'idle',label:'在卧室休息',angle:.50,dwell:7}
};
export class Routine {
    constructor(pickCrop,onCare,onDecision){
        this.pickCrop=pickCrop; this.onCare=onCare;
        this.x=points.home[0];this.z=points.home[1];this.node='home';this.path=[];
        this.place='home';this.job={...destinations.home};this.kind='idle';this.label=this.job.label;
        this.clock=0;this.yaw=.5;this.facing=.5;
        this.onDecision=onDecision;this.goal=null;this.pending=false;this.revision=0;
    }
    go(place,goal=null){
        this.revision++;this.goal=goal;this.outcome='';
        this.place=place;this.job={...destinations[place]};
        if(place==='garden'){
            const care=this.pickCrop(); Object.assign(this.job,care);
            this.job.node='bed'+(care.plotId%4);
            this.job.angle=care.plotId<4?0:Math.PI;
        }
        // Finish the segment already underfoot before turning onto the new path.
        const next=this.path[0]??this.node;
        this.path=[...(this.path.length?[next]:[]),...route(next,this.job.node)];
        this.clock=0;
        if(this.path.length){
            this.kind='walk';this.label='去'+({desk:'书桌',living:'客厅',garden:'菜园',street:'花店',bookshop:'书屋',home:'卧室'})[place]+'的路上';
        }else this.arrive();
    }
    arrive(){
        this.kind=this.job.kind;this.label=this.job.label;this.facing=this.job.angle;this.clock=0;
    }
    update(dt){
        if(this.path.length){
            let distance=dt*1.48;
            while(this.path.length&&distance>0){
                const node=this.path[0],[x,z]=points[node],dx=x-this.x,dz=z-this.z;
                const d=Math.hypot(dx,dz);
                if(d>.001)this.facing=Math.atan2(dx,dz);
                if(d<=distance){this.x=x;this.z=z;this.node=this.path.shift();distance-=d;}
                else{this.x+=dx/d*distance;this.z+=dz/d*distance;distance=0;}
            }
            if(!this.path.length)this.arrive();
        }else{
            const previous=this.clock;this.clock+=dt;
            if(this.place==='garden'&&previous<3&&this.clock>=3)this.outcome=this.onCare(this.job);
            if(this.clock>=this.job.dwell&&!this.pending){
                this.pending=true;
                const revision=this.revision;
                this.onDecision(this.goal,this.outcome||this.label).then(goal=>{
                    if(revision===this.revision)this.go(goal.place,goal);
                }).catch(()=>{this.clock=0;this.label='等小窝重新连上。';}).finally(()=>this.pending=false);
            }
        }
        const turn=this.facing-this.yaw;
        this.yaw+=Math.atan2(Math.sin(turn),Math.cos(turn))*(1-Math.exp(-dt*9));
    }
}
