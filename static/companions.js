import * as T from './vendor/three.module.js';

// Positions, rest-pose projections and triangle indices are baked from aligned silhouettes.
const vertexShader=`
    attribute vec2 profileUV;
    attribute vec2 backUV;
    attribute float longitude;
    attribute vec3 quarterUV;

    varying vec2 vFront, vSide, vRear, vRadial;
    varying vec3 vQuarter;
    void main() {
        vFront=uv; vSide=profileUV; vRear=backUV;
        vQuarter=quarterUV;
        vRadial=vec2(sin(longitude),cos(longitude));
        gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);
    }
`;

export function makeCompanion(look) {
    const root=new T.Group();
    const prefix='/static/pet/figure-'+look;
    const loader=new T.TextureLoader();
    const uniforms={viewer:{value:new T.Vector2(0,1)}};
    const bodyMaterial=new T.ShaderMaterial({vertexShader,fragmentShader,uniforms});
    const limbUniforms={fabric:{value:null},lining:{value:null},eye:{value:new T.Vector3()}};
    const limbMaterial=new T.ShaderMaterial({
        uniforms:limbUniforms,
        vertexShader:`
            attribute vec2 sideUV; varying vec2 art,side; varying vec3 n,p;
            void main(){art=uv;side=sideUV;n=normal;p=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}
        `,
        fragmentShader:`
            uniform sampler2D fabric,lining;uniform vec3 eye;
            varying vec2 art,side;varying vec3 n,p;
            void main(){
                float front=smoothstep(.15,.55,normalize(n).z)*smoothstep(-.02,.37,normalize(eye-p).z);
                gl_FragColor=vec4(mix(texture2D(lining,side).rgb,texture2D(fabric,art).rgb,front),1.);
                #include <colorspace_fragment>
            }
        `});
    const joints={};
    const pen=new T.Mesh(new T.CylinderGeometry(.006,.007,.11,16),new T.MeshStandardMaterial({color:0x3e6971,roughness:.45}));
    const ferrule=new T.Mesh(new T.CylinderGeometry(.007,.0075,.015,16),new T.MeshStandardMaterial({color:0xd8bb7a,metalness:.5,roughness:.45}));
    ferrule.position.y=-.052;pen.add(ferrule);
    const nib=new T.Mesh(new T.ConeGeometry(.0068,.024,10),new T.MeshStandardMaterial({color:0x454652,metalness:.3}));
    nib.rotation.z=Math.PI;nib.position.y=-.071;pen.add(nib);
    const cameraLocal=new T.Vector3();
    pen.visible=false;

    // Each chain has six rigid solids per side. Coordinates are authored in one common
    // rest pose. Convert once into joint-local coordinates, then rotate the parent joints.
    const ready=Promise.all([
        fetch(prefix+'.rig').then(async res=>{
            if(!res.ok)throw Error('未能读取角色关节模型');
            const bytes=await res.arrayBuffer();
            const metaSize=new DataView(bytes).getUint32(0,true);
            const nodes=JSON.parse(new TextDecoder().decode(new Uint8Array(bytes,4,metaSize)));
            const raw=new Uint8Array(bytes,4+metaSize);
            const pivots=new Map();
            for(const node of nodes){
                const {name,parent,count,pivot,offset,indices}=node;
                const body=node.atlas==='body';
                const stride=body?10:4;
                const pEnd=offset+6*count,uvEnd=pEnd+stride*2*count;
                const packed=new Int16Array(raw.slice(offset,pEnd).buffer);
                const atlas=new Int16Array(raw.slice(pEnd,uvEnd).buffer);
                const geometry=new T.BufferGeometry();
                const positions=Float32Array.from(packed,(v,i)=>v/16000-pivot[i%3]);
                geometry.setAttribute('position',new T.BufferAttribute(positions,3));
                const mappings=body?[['uv',2],['profileUV',2],['backUV',2],['longitude',1],['quarterUV',3]]:[['uv',2],['sideUV',2]];
                let column=0;
                for(const [key,size] of mappings){
                    const attr=new Float32Array(count*size);
                    const factor=key==='longitude'?Math.PI/30000:1/30000;
                    for(let i=0;i<count;i++){
                        for(let j=0;j<size;j++)attr[i*size+j]=atlas[i*stride+column+j]*factor;
                    }
                    geometry.setAttribute(key,new T.BufferAttribute(attr,size));column+=size;
                }
                const index=new Uint32Array(raw.slice(uvEnd,uvEnd+indices*4).buffer);
                geometry.setIndex(new T.BufferAttribute(index,1));
                if(!body)geometry.computeVertexNormals();
                const joint=new T.Mesh(geometry,body?bodyMaterial:limbMaterial);
                joint.name=name;joints[name]=joint;
                joint.position.fromArray(pivot);
                pivots.set(name,joint.position.clone());
                if(parent)joint.position.sub(pivots.get(parent));
                (parent?joints[parent]:root).add(joint);
                if(body)joint.onBeforeRender=(_renderer,_scene,camera)=>{
                    camera.getWorldPosition(cameraLocal);joint.worldToLocal(cameraLocal);
                    uniforms.viewer.value.set(cameraLocal.x,cameraLocal.z).normalize();
                };
                else joint.onBeforeRender=(_renderer,_scene,camera)=>{
                    camera.getWorldPosition(cameraLocal);
                    limbUniforms.eye.value.copy(joint.worldToLocal(cameraLocal));
                    limbMaterial.uniformsNeedUpdate=true;
                };
            }
            joints.handR.add(pen);
            pen.position.set(.002,-.030,.027);pen.rotation.x=.64;pen.rotation.z=-.22;
        }),
        ...['front','profile','back','left','right','limbs','lining'].map(async side=>{
            const map=await loader.loadAsync(prefix+'-'+side+'.webp');
            map.colorSpace=T.SRGBColorSpace;map.anisotropy=4;
            if(side==='limbs')limbUniforms.fabric.value=map;
            else if(side==='lining')limbUniforms.lining.value=map;
            else uniforms[(side==='back'?'rear':side)+'Map']={value:map};
        })
    ]);
    return {root,ready,joints,animate(t,kind){
        const walk=kind==='walk', write=kind==='write', read=kind==='read', play=kind==='play';
        const garden=['plant','water','harvest','till'].includes(kind);
        const beat=Math.sin(t*8.5);
        joints.body.position.y=walk?.011*Math.abs(beat):.002*Math.sin(t*1.8);
        joints.body.rotation.x=write?.026:garden?.044:0;
        joints.body.rotation.z=walk?.018*beat:play?.023*Math.sin(t*3.5):0;
        joints.body.rotation.y=kind==='watch'?.13*Math.sin(t*.9):0;
        pen.visible=write;
        for(const suffix of ['R','L']){
            const right=suffix==='R', sign=right?-1:1;
            const forward=sign*beat, knee=walk?Math.max(0,-forward):0;
            const toss=Math.sin(t*3.5+sign*.9);
            let shoulder=0,elbow=-.07,wrist=0,spread=0;
            if(walk){shoulder=.45*forward;elbow=-.24+.13*forward;}
            if(write){
                shoulder=right?-.82:-.46;
                elbow=right?-.79+.12*Math.sin(t*6.1):-.46;
                wrist=right?.22+.13*Math.cos(t*6.1):.16;
                spread=right?.11:.06;
            }
            if(read){shoulder=-.65;elbow=-.78;wrist=.20;spread=.07;}
            if(play){shoulder=-.86+.38*toss;elbow=-.75+.40*toss;wrist=.19*toss;spread=.23;}
            if(garden){
                shoulder=right?-.85-.19*Math.sin(t*3.15):-.56;
                elbow=right?-.60-.17*Math.cos(t*3.15):-.36;
                wrist=kind==='water'?-.16*Math.sin(t*2):.12;spread=.08;
            }
            joints['upperArm'+suffix].rotation.set(shoulder,sign*(write||read?-.24:0),sign*spread);
            joints['forearm'+suffix].rotation.x=elbow;
            joints['hand'+suffix].rotation.set(wrist,0,write&&right?.13*Math.sin(t*5):0);
            joints['thigh'+suffix].rotation.x=walk?-(look==='A'?.39:.49)*forward:garden?-.07:0;
            joints['shin'+suffix].rotation.x=walk?.07+(look==='A'?.62:.75)*knee:garden?.13:0;
            joints['foot'+suffix].rotation.x=walk?.24*forward-.32*knee:garden?-.06:0;
        }
    }};
}
const fragmentShader=`
    uniform sampler2D frontMap,profileMap,rearMap,leftMap,rightMap;
    uniform vec2 viewer;
    varying vec2 vFront,vSide,vRear,vRadial;
    varying vec3 vQuarter;
    void main() {
        vec2 n=normalize(vRadial);
        // Keep a head-on view registered to the drawing. As the camera orbits, favour
        // the painted projection corresponding to the visible half of the volume.
        // Keep inked eyes and hairpins steady within a view. Mixing source
        // drawings based on individual vertices gives the face a broken seam.
        vec2 direction=viewer;
        float angle=abs(atan(direction.x,direction.y));
        float sq=smoothstep(.325,.363,angle);
        float sf=smoothstep(.975,1.022,angle);
        float sr=smoothstep(2.30,2.36,angle);
        vec3 front=texture2D(frontMap,vFront).rgb;
        vec3 side=texture2D(profileMap,vSide).rgb;
        vec3 rear=texture2D(rearMap,vRear).rgb;
        vec3 quarter=direction.x>=0.?texture2D(leftMap,vQuarter.xz).rgb:texture2D(rightMap,vQuarter.yz).rgb;
        gl_FragColor=vec4(mix(mix(mix(front,quarter,sq),side,sf),rear,sr),1.);
        #include <colorspace_fragment>
    }
`;

