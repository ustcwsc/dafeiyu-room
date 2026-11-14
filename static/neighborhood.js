import * as T from './vendor/three.module.js';

// A pedestrian lane along the west face of the house. The storefronts face +X.
export function buildStreet(scene) {
    const group=new T.Group();group.name='海风街';scene.add(group);
    const materials=new Map(), cube=new T.BoxGeometry(), ball=new T.IcosahedronGeometry(1,1);
    function mesh(geo,color,x,y,z,sx,sy,sz){
        if(!materials.has(color))materials.set(color,new T.MeshStandardMaterial({color,roughness:.83}));
        const m=new T.Mesh(geo,materials.get(color));m.position.set(x,y,z);m.scale.set(sx,sy,sz);
        m.castShadow=true;m.receiveShadow=true;group.add(m);return m;
    }
    const box=(color,x,y,z,w,h,d)=>mesh(cube,color,x,y,z,w,h,d);
    const pole=new T.CylinderGeometry(1,1,1,12);
    const cyl=(color,x,y,z,r,h)=>mesh(pole,color,x,y,z,r,h,r);
    box(0x91a586,-7,-.18,.25,12,.23,18.5);
    box(0x8f9b9e,-4.15,-.018,.25,2.5,.09,18.5);
    for(const x of [-6.15,-2.20])box(0xdbcab1,x,.004,.25,1.55,.08,18.5);
    for(let i=-8;i<=9;i++){
        for(const x of [-6.15,-2.20])box(0xbcad95,x,.046,i,1.54,.006,.01);
    }
    for(let i=0;i<5;i++)box(0xffedcb,-4.14,.031,5.55+i*.22,1.72,.011,.105);
    box(0xd6cfb4,-1.3,.016,6.24,1.58,.049,.94);
    function sign(word,x,y,z,board,ink,width){
        const c=document.createElement('canvas');c.width=512;c.height=116;
        const ctx=c.getContext('2d');ctx.fillStyle=board;ctx.fillRect(0,0,c.width,c.height);
        ctx.strokeStyle=ink;ctx.lineWidth=3;ctx.strokeRect(8,8,496,100);
        ctx.fillStyle=ink;ctx.font='bold 63px "Microsoft YaHei",sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(word,256,58);
        const texture=new T.CanvasTexture(c);texture.colorSpace=T.SRGBColorSpace;
        const m=new T.Mesh(new T.PlaneGeometry(width,width*116/512),new T.MeshBasicMaterial({map:texture,toneMapped:false}));
        m.rotation.y=Math.PI/2;m.position.set(x,y,z);group.add(m);
    }
    for(const [z,base,accent,word] of [[4.85,0xf5ceaa,0xaa594b,'面包房'],[.4,0xb1c9b4,0x478578,'花  舍'],[-4.05,0xf0d9b2,0x557795,'海风书屋']]){
        box(base,-8.6,1.41,z,3.5,2.8,4.25);
        box(accent,-8.6,2.87,z,3.68,.17,4.39);
        box(0xf2e6ce,-8.6,3.06,z,3.48,.24,4.21);
        for(const dz of [-1.33,.19]){
            box(0xf4e3c0,-6.825,1.03,z+dz,.11,1.30,1.18);
            box(0x567476,-6.744,1.03,z+dz,.055,1.12,1.02);
            box(0xb8d4cb,-6.708,1.22,z+dz,.022,.57,.93);
            box(0xeed6ae,-6.689,1.03,z+dz,.04,1.12,.035);
            box(0xeed6ae,-6.689,1.07,z+dz,.04,.035,1.02);
        }
        box(accent,-6.79,.93,z+1.39,.09,1.79,.77);
        box(0xc8ded5,-6.725,1.17,z+1.39,.04,1.13,.56);
        sign(word,-6.765,2.58,z,'#f5e8d1','#35534b',1.84);
        for(let i=0;i<14;i++){
            const col=i%2?0xf6ead0:accent, dz=z-1.99+i*.305;
            const canopy=box(col,-6.44,2.17,dz,.88,.065,.307);canopy.rotation.z=-.25;
            box(col,-6.02,1.999,dz,.045,.14,.307);
        }
        // Baked loaves, flower pots and books distinguish the three shop displays.
        box(0xa06f4d,-6.38,.53,z-.49,.43,.09,1.69);
        for(const side of [-.69,.69])box(0x806447,-6.39,.26,z-.49+side,.25,.47,.08);
        for(let i=0;i<6;i++){
            const zz=z-1.13+i*.239;
            if(word==='面包房'){
                mesh(ball,0xdba35d,-6.36,.65,zz,.14,.09,.10);
                box(0xf1c58b,-6.32,.724,zz,.076,.01,.025);
            }else if(word==='花  舍'){
                cyl(0xaa7056,-6.37,.67,zz,.09,.15);mesh(ball,0x739779,-6.37,.84,zz,.09,.14,.10);
                mesh(ball,i%2?0xf5ac8d:0xeac25d,-6.34,.98,zz,.059,.054,.055);
            }else{
                box([0xa75c4d,0x5e8893,0xceb568][i%3],-6.35,.72,zz,.22,.30,.09).rotation.x=.11;
            }
        }
    }
    for(const z of [-7.1,-2.8,2.2,7.8]){
        cyl(0xac987c,-1.76,.15,z,.36,.24);
        cyl(0x856b50,-1.76,.85,z,.1,1.55);
        mesh(ball,0x78a384,-1.76,1.88,z,.49,.70,.48);
        mesh(ball,0x8eaf79,-1.81,2.21,z+.09,.44,.48,.39);
    }
    for(const z of [-4.8,4.1]){
        cyl(0x455858,-5.3,1.05,z,.044,2.12);
        cyl(0x455858,-5.3,.12,z,.13,.22);
        mesh(ball,0xffdf9d,-5.3,2.25,z,.16,.22,.16);
        cyl(0x455858,-5.3,2.47,z,.17,.055);
    }
    for(const z of [-1.7,2.8]){
        for(const dz of [-.43,.43])box(0x465b59,-2.27,.20,z+dz,.42,.37,.075);
        for(let i=0;i<3;i++)box(0xbc885f,-2.43+.14*i,.41,z,.12,.068,1.16);
        for(const y of [.59,.74])box(0xc1936a,-2.51,y,z,.065,.095,1.16);
    }
    sign('海风街',-2.89,1.86,5.82,'#496f70','#f6e8c8',.90);
    cyl(0x65716c,-2.94,.91,5.82,.033,1.82);
    return group;
}
