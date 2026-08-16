/**
 * pipeline — revamped vanilla frontend
 * - minimal UI, no batch artifacts
 * - Run + Stop (AbortController)
 * - 3D via OrbitControls
 */
const $ = (s, r=document) => r.querySelector(s);
const apiBase = "";
let currentStream = null;
let rafId = null;
let abortCtrl = null;
let vrmInst = null;

function edgesFromJoints(spec){ return spec.filter(j=>j.parent).map(j=>({from:j.parent,to:j.name})); }

function lerp(a,b,t){ return a*(1-t)+b*t; }
function interpJoints(a,b,t){
  if(!a) return b; if(!b) return a;
  return [lerp(a[0],b[0],t), lerp(a[1],b[1],t), lerp(a[2],b[2],t), Math.max(a[3],b[3])];
}
function create2DRenderer(canvas){
  const ctx=canvas.getContext("2d");
  const W=canvas.width, H=canvas.height;
  const state={frames:[], jointsSpec:[], fps:30, edges:[]};
  function setStream(stream){
    state.frames=stream.frames||[];
    state.jointsSpec=stream.meta?.joints||[];
    state.edges=edgesFromJoints(state.jointsSpec);
    state.fps=stream.meta?.fps||30;
    drawFrame(0);
  }
  function project(v){
    const scale=185;
    const is3d = String(currentStream?.meta?.space||"").includes("world");
    const persp = is3d ? 1/(1+Math.max(0,v[2])*0.45) : 1;
    return [W/2+v[0]*scale*persp, H/2 - v[1]*scale*persp];
  }
  function drawFrame(idx){
    drawFrameLerp(idx,0);
  }
  function drawFrameLerp(idx, alpha){
    const f0=state.frames[Math.max(0,Math.min(idx,state.frames.length-1))];
    const f1=state.frames[Math.max(0,Math.min(idx+1,state.frames.length-1))];
    if(!f0) return;
    // build interpolated joints
    const joints={};
    const names=new Set([...Object.keys(f0.joints), ...Object.keys(f1?.joints||{})]);
    for(const n of names){
      const a=f0.joints[n], b=f1?.joints[n];
      if(!a&&!b) continue;
      if(!a||!b) { joints[n]=a||b; continue; }
      joints[n]= alpha>0 ? interpJoints(a,b,alpha) : a;
    }
    const f={joints};
    ctx.clearRect(0,0,W,H);
    ctx.fillStyle="#0f141e"; ctx.fillRect(0,0,W,H);
    ctx.strokeStyle="rgba(80,100,140,.12)"; ctx.lineWidth=1;
    for(let x=0;x<W;x+=80){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke()}
    for(let y=0;y<H;y+=80){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke()}
    for(const e of state.edges){
      const a=f.joints[e.from], b=f.joints[e.to];
      if(!a||!b) continue;
      if(a[3]<0.3||b[3]<0.3) continue;
      const [ax,ay]=project(a),[bx,by]=project(b);
      ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);
      ctx.strokeStyle="rgba(255,160,40,.9)";ctx.lineWidth=5;ctx.lineCap="round";ctx.stroke();
      ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);
      ctx.strokeStyle="rgba(120,240,255,.95)";ctx.lineWidth=2.5;ctx.stroke();
    }
    for(const [name,v] of Object.entries(f.joints)){
      if(!v) continue; if(v[3]<0.3) continue;
      const [x,y]=project(v);
      const r=name==="head"?6:3.5;
      ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);
      ctx.fillStyle=(name==="lHand"||name==="rHand")?"#7dff9b":"#fff";ctx.fill();
      ctx.strokeStyle="rgba(255,255,255,.9)";ctx.lineWidth=1;ctx.stroke();
    }
  }
  return {setStream, drawFrame, drawFrameLerp, state};
}

// 3D with OrbitControls
async function create3DRenderer(host, stream){
  if(host._renderer){
    host._renderer.stream=stream;
    host._renderer.edges=edgesFromJoints(stream.meta.joints);
    host._renderer.setFrame(0);
    return host._renderer;
  }
  let THREE, OrbitControls;
  try{
    THREE = await import("three");
    ({OrbitControls} = await import("three/addons/controls/OrbitControls.js"));
  }catch(e){
    console.error("[3d] import failed",e);
    host.innerHTML='<div style="color:#9aa3b2;padding:20px">Three.js failed to load.<br><small>'+String(e)+'</small></div>';
    return null;
  }
  host.style.display="block";
  const W=host.clientWidth||640, H=host.clientHeight||host.clientWidth||640;
  const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0b0d12);
  const camera=new THREE.PerspectiveCamera(45,W/H,0.1,100); camera.position.set(0,0.9,2.2);
  const renderer=new THREE.WebGLRenderer({antialias:true}); renderer.setSize(W,H);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
  host.innerHTML=""; host.appendChild(renderer.domElement);
  scene.add(new THREE.GridHelper(3.2,16,0x3355aa,0x18243a));
  scene.add(new THREE.AxesHelper(0.9));
  const edges=edgesFromJoints(stream.meta.joints);
  const coreGeo=new THREE.BufferGeometry(), haloGeo=new THREE.BufferGeometry(), jointGeo=new THREE.BufferGeometry();
  const coreMat=new THREE.LineBasicMaterial({color:0x55e6ff,transparent:true,opacity:.9});
  const haloMat=new THREE.LineBasicMaterial({color:0x00a8ff,transparent:true,opacity:.14});
  const jointMat=new THREE.PointsMaterial({color:0xffffff,size:0.055,sizeAttenuation:true});
  const core=new THREE.LineSegments(coreGeo,coreMat), halo=new THREE.LineSegments(haloGeo,haloMat), joints=new THREE.Points(jointGeo,jointMat);
  for(const o of [core,halo,joints]) o.frustumCulled=false;
  scene.add(halo); scene.add(core); scene.add(joints);
  const controls=new OrbitControls(camera, renderer.domElement);
  controls.target.set(0,0.15,0); controls.enableDamping=true; controls.dampingFactor=0.08;
  controls.minDistance=0.8; controls.maxDistance=5; controls.update();
  window.addEventListener("resize",()=>{
    const w=host.clientWidth||640, h=host.clientHeight||host.clientWidth||640;
    camera.aspect=w/h; camera.updateProjectionMatrix(); renderer.setSize(w,h);
  });
  let currentStream=stream, currentEdges=edges;
  function lerp(a,b,t){ return a*(1-t)+b*t; }
  function setFrame(idx){ setFrameLerp(idx,0); }
  function setFrameLerp(idx, alpha){
    const f0=currentStream.frames[Math.max(0,Math.min(idx,currentStream.frames.length-1))];
    const f1=currentStream.frames[Math.max(0,Math.min(idx+1,currentStream.frames.length-1))];
    if(!f0) return;
    // build interpolated joints
    const get = (f, name)=> f.joints[name];
    const jointsInterp={};
    for(const spec of currentStream.meta.joints){
      const a=get(f0,spec.name), b=get(f1,spec.name);
      if(!a&&!b) continue;
      if(!a||!b) { jointsInterp[spec.name]=a||b; continue; }
      jointsInterp[spec.name]= alpha>0 ? [lerp(a[0],b[0],alpha), lerp(a[1],b[1],alpha), lerp(a[2],b[2],alpha), Math.max(a[3],b[3])] : a;
    }
    const pos=[];
    for(const spec of currentStream.meta.joints){
      const v=jointsInterp[spec.name]; if(!v) continue; if(v[3]<0.35) continue;
      pos.push(v[0],v[1],v[2]);
    }
    jointGeo.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(pos),3));
    jointGeo.computeBoundingSphere();
    const epos=[], hpos=[];
    for(const e of currentEdges){
      const a=jointsInterp[e.from], b=jointsInterp[e.to]; if(!a||!b) continue;
      if(a[3]<0.35||b[3]<0.35) continue;
      epos.push(a[0],a[1],a[2], b[0],b[1],b[2]);
      const dx=b[0]-a[0], dy=b[1]-a[1], dz=b[2]-a[2];
      const m=0.06; hpos.push(a[0]-dx*m,a[1]-dy*m,a[2]-dz*m, b[0]+dx*m,b[1]+dy*m,b[2]+dz*m);
    }
    coreGeo.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(epos),3));
    coreGeo.computeBoundingSphere();
    haloGeo.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(hpos),3));
    haloGeo.computeBoundingSphere();
    if(idx===0 && alpha===0) console.log("[3d] setFrame 0", {joints:pos.length/3, edges:epos.length/6, stream:currentStream.meta.space});
  }
  (function loop(){
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene,camera);
  })();
  host._renderer={get stream(){return currentStream}, set stream(s){currentStream=s; currentEdges=edgesFromJoints(s.meta.joints)}, setFrame, setFrameLerp, scene, camera, renderer, controls};
  setFrame(0);
  return host._renderer;
}

// wiring
const srcVideo=$("#srcVideo"), noVideo=$("#noVideo"), skel2d=$("#skel2d"), skel3dHost=$("#skel3dHost"), vrmHost=$("#vrmHost");
const r2d=create2DRenderer(skel2d);
const health=$("#health");
async function checkHealth(){
  try{
    const res=await fetch(`${apiBase}/api/health`); const j=await res.json();
    const exts=j.extractors||[];
    health.className="health ok";
    health.title=`extractors: ${exts.join(", ")} | cuda:${j.cuda} | smplx:${j.smplx_available?"ok":"missing"} | torch:${j.torch||"no"}`;
    // keep all 5 options visible but mark smplx as disabled if not available (per user: return 501, don't hide)
    const smplxOpts = ["hybrid_smplx_mediapipe","smplx_full"];
    const sel=$("#extractorSel");
    for(const opt of sel.options){
      if(smplxOpts.includes(opt.value)){
        opt.disabled = !j.smplx_available;
        opt.textContent = opt.disabled ? `${opt.value} (needs SMPLX in .models/smplx/)` : opt.value;
        opt.title = j.smplx_detail||"";
      }
    }
    // show hint if smplx missing
    if(!j.smplx_available){
      console.log("[health] smplx not configured:", j.smplx_detail);
    }
  }catch{ health.className="health bad"; health.title="api offline"; }
}
function setStatus(msg,isError=false){ const el=$("#status"); el.textContent=msg; el.style.color=isError?"#b91c1c":"#6b7280"; }
function clearWarn(){ const w=$("#estimatorWarn"); w.classList.add("hidden"); w.textContent=""; }
function showWarn(msg){ const w=$("#estimatorWarn"); w.textContent=msg; w.classList.remove("hidden"); }

let pendingFiles=null;
const runBtn=$("#runBtn"), stopBtn=$("#stopBtn"), browseBtn=$("#browseBtn"), fileInput=$("#fileInput"), selectedInfo=$("#selectedInfo");

function setPendingFiles(list){
  pendingFiles=list && list.length ? Array.from(list) : null;
  const n=pendingFiles?pendingFiles.length:0;
  runBtn.disabled=n===0;
  if(n===1) selectedInfo.textContent=`${pendingFiles[0].name} — ${(pendingFiles[0].size/1024/1024).toFixed(2)} MB`;
  else if(n>1) selectedInfo.textContent=`${n} videos selected`;
  else selectedInfo.textContent="";
  if(n>=1){
    const url=URL.createObjectURL(pendingFiles[0]);
    srcVideo.src=url; srcVideo.classList.add("has-src"); noVideo.style.display="none"; srcVideo.load();
    setStatus(`Ready — ${n} file(s) — hit Run`);
  }
}

async function uploadFiles(list){
  if(!list||!list.length) return;
  const space=$("#spaceSel").value, extractor=$("#extractorSel").value;
  const bar=$("#progress"), barFill=$("#progressBar");
  bar.classList.remove("hidden"); barFill.style.width="10%";
  runBtn.disabled=true; stopBtn.classList.remove("hidden"); runBtn.textContent="⏳ Running…";
  abortCtrl=new AbortController();
  clearWarn(); setStatus(`Running ${extractor}/${space} …`);
  try{
    if(list.length===1){
      const fd=new FormData(); fd.append("file", list[0]);
      barFill.style.width="35%";
      const res=await fetch(`${apiBase}/api/extract?space=${space}&extractor=${extractor}`,{method:"POST", body:fd, signal:abortCtrl.signal});
      barFill.style.width="85%";
      if(!res.ok){
        // handle 501 for SMPLX missing assets
        if(res.status===501){
          let detail="SMPL-X not configured";
          try{ const j=await res.json(); detail=j.detail||detail; if(j.hint) detail+=` — ${j.hint}`; }catch{}
          throw new Error(`501 ${detail}`);
        }
        throw new Error(`${res.status} ${await res.text()}`);
      }
      const data=await res.json();
      currentStream=data.stream; barFill.style.width="100%";
      onStreamReady(data);
      if(String(data.estimator).includes("dummy")) showWarn(`Synthetic — ${data.estimator}`);
      else if(!data.stream.frames.some(f=>f.joints&&f.joints.hips)) showWarn(`No person detected — try brighter, centered video.`);
      setStatus(`Done — ${data.frameCount} frames @ ${data.fps} fps · ${data.estimator}`);
    }else{
      const fd=new FormData(); for(const f of list) fd.append("files",f);
      const res=await fetch(`${apiBase}/api/extract-batch?space=${space}&extractor=${extractor}`,{method:"POST", body:fd, signal:abortCtrl.signal});
      if(!res.ok){
        if(res.status===501){
          let detail="SMPL-X not configured";
          try{ const j=await res.json(); detail=j.detail||detail; }catch{}
          throw new Error(`501 ${detail}`);
        }
        throw new Error(`${res.status} ${await res.text()}`);
      }
      const data=await res.json();
      // show first result in viewer
      const first=data.results.find(r=>!r.error);
      if(first){ currentStream=first.stream; onStreamReady(first); }
      else {
        // all failed (e.g., 501) — surface first error
        const err=data.results[0]?.error||"unknown";
        showWarn(err);
        setStatus(err, true);
      }
      if(data.results.some(r=>r.status===501)) showWarn(`SMPL-X missing in pipeline/.models/smplx/ — place SMPLX_NEUTRAL.* there (no auto-download)`);
      else setStatus(`Batch done — ${data.count} videos`);
      barFill.style.width="100%";
    }
  }catch(e){
    if(e.name==="AbortError"){ setStatus("Stopped — pipeline aborted.", true); }
    else if(String(e).includes("501")){ console.warn(e); setStatus(String(e), true); showWarn(String(e)); }
    else{ console.error(e); setStatus(String(e), true); showWarn(String(e)); }
  }finally{
    abortCtrl=null; runBtn.disabled=false; runBtn.textContent="▶ Run"; stopBtn.classList.add("hidden");
    setTimeout(()=>{ bar.classList.add("hidden"); barFill.style.width="0%"; },900);
  }
}

function onStreamReady(data){
  $("#skeletonMeta").textContent=`${data.frameCount} frames · ${data.duration.toFixed(2)}s`;
  $("#frameLabel").textContent=`0 / ${data.frameCount}`;
  const dlJson=$("#dlJson"), dlMp4=$("#dlMp4");
  dlJson.href=`${apiBase}${data.outputs.json}`; dlJson.classList.remove("hidden"); dlJson.download=data.run_id+".json";
  dlMp4.href=`${apiBase}${data.outputs.skeletonVideo}`; dlMp4.classList.remove("hidden"); dlMp4.download=data.run_id+"_skeleton.mp4";
  r2d.setStream(data.stream);
  if(skel3dHost._renderer) skel3dHost._renderer.stream=data.stream;
  if(vrmInst){ vrmInst.setStream(data.stream); $("#vrmMeta").textContent=`${data.frameCount} frames`; }
  $("#playBoth").disabled=false; $("#scrub").disabled=false;
  $("#scrub").max=Math.max(0,data.frameCount-1); $("#scrub").value=0;
  if($("#viewSel").value==="3d") init3DView(data.stream);
  wireSync();
}
function getFrameIdxForTime(t){
  const frames=currentStream?.frames||[];
  if(!frames.length) return 0;
  // use timestamp search instead of Math.floor(t*fps) to avoid snap when fps mismatched
  // frames are sorted by timestamp = idx / fps from backend probe
  // binary search for largest timestamp <= t
  let lo=0, hi=frames.length-1, ans=0;
  while(lo<=hi){
    const mid=(lo+hi>>1);
    if(frames[mid].timestamp <= t) { ans=mid; lo=mid+1; } else hi=mid-1;
  }
  return ans;
}
let syncRaf=null;
function wireSync(){
  if(!currentStream) return;
  const fps=currentStream.meta.fps||30;
  function onTime(){
    let t=srcVideo.currentTime||0;
    // handle fps/duration mismatch: scale t to stream duration if video duration differs (common when probe fps != browser duration)
    const streamDur=currentStream.duration||currentStream.frames.length/fps;
    const vidDur=srcVideo.duration||streamDur;
    if(vidDur && streamDur && Math.abs(vidDur-streamDur)>0.05){
      t = t * (streamDur / vidDur);
    }
    const idx=getFrameIdxForTime(t);
    const f0=currentStream.frames[idx], f1=currentStream.frames[idx+1];
    let alpha=0;
    if(f1 && f0 && f1.timestamp > f0.timestamp){
      alpha = Math.min(1, Math.max(0, (t - f0.timestamp) / (f1.timestamp - f0.timestamp)));
    }
    // lerp draw for smooth (fixes snap-to-frame)
    if(r2d.drawFrameLerp) r2d.drawFrameLerp(idx, alpha);
    else r2d.drawFrame(idx);
    $("#scrub").value=String(idx);
    $("#frameLabel").textContent=`${idx} / ${currentStream.frames.length}`;
    $("#frameCount").textContent=`f ${idx} / ${currentStream.frames.length}`;
    $("#timeLabel").textContent=`${t.toFixed(2)}s / ${streamDur.toFixed(2)}s`;
    if(skel3dHost._renderer){
      if(skel3dHost._renderer.setFrameLerp) skel3dHost._renderer.setFrameLerp(idx, alpha);
      else skel3dHost._renderer.setFrame(idx);
    }
    if(vrmInst) vrmInst.setFrameLerp(idx, alpha);
  }
  // remove old listeners
  srcVideo.removeEventListener("timeupdate", srcVideo._onTime||(()=>{}));
  srcVideo._onTime=onTime;
  // use timeupdate as fallback, but primary is RAF / requestVideoFrameCallback
  srcVideo.addEventListener("timeupdate", onTime);
  // continuous RAF while playing — fixes freezing/snap (timeupdate only fires ~4Hz)
  function startLoop(){
    if(syncRaf) cancelAnimationFrame(syncRaf);
    const loop=()=>{
      if(!srcVideo.paused && !srcVideo.ended){
        onTime();
        syncRaf=requestAnimationFrame(loop);
      }
    };
    loop();
  }
  function stopLoop(){ if(syncRaf) cancelAnimationFrame(syncRaf); syncRaf=null; }
  srcVideo.removeEventListener("play", srcVideo._onPlayLoop||(()=>{}));
  srcVideo.removeEventListener("pause", srcVideo._onPauseLoop||(()=>{}));
  srcVideo._onPlayLoop=startLoop; srcVideo._onPauseLoop=stopLoop;
  srcVideo.addEventListener("play", startLoop);
  srcVideo.addEventListener("pause", stopLoop);
  // also handle seeking
  srcVideo.addEventListener("seeked", onTime);
  // scrub uses timestamp scaled to video duration, with lerp
  $("#scrub").oninput=e=>{
    const idx=parseInt(e.target.value,10);
    const ts=currentStream.frames[idx]?.timestamp ?? idx/fps;
    const streamDur=currentStream.duration||currentStream.frames.length/fps;
    const vidDur=srcVideo.duration||streamDur;
    const videoTs = (vidDur/streamDur)*ts;
    if(Math.abs(srcVideo.currentTime - videoTs) > 0.01) srcVideo.currentTime=videoTs;
    if(r2d.drawFrameLerp) r2d.drawFrameLerp(idx,0); else r2d.drawFrame(idx);
    if(skel3dHost._renderer){
      if(skel3dHost._renderer.setFrameLerp) skel3dHost._renderer.setFrameLerp(idx,0);
      else skel3dHost._renderer.setFrame(idx);
    }
    if(vrmInst) vrmInst.setFrameLerp(idx,0);
  };
  $("#playBoth").onclick=()=>{
    if(srcVideo.paused) srcVideo.play();
    else srcVideo.pause();
  };
  // initial draw
  onTime();
}
async function init3DView(stream){
  skel3dHost.classList.remove("hidden"); skel2d.classList.add("hidden");
  $("#hint3d").classList.remove("hidden");
  const inst=await create3DRenderer(skel3dHost, stream||currentStream);
  if(inst&&stream){ inst.stream=stream; inst.setFrame(0); }
}
function updateViewMode(){
  const m=$("#viewSel").value;
  if(m==="3d"){
    if(currentStream) init3DView(currentStream);
    else{ skel3dHost.classList.remove("hidden"); skel2d.classList.add("hidden"); skel3dHost.innerHTML='<div style="color:#9aa3b2;padding:40px;text-align:center">Run pipeline first — 3D view appears here</div>'; $("#hint3d").classList.remove("hidden"); }
  }else{
    skel3dHost.classList.add("hidden"); skel2d.classList.remove("hidden"); $("#hint3d").classList.add("hidden");
  }
}

// events — robust wiring after DOM ready
function bindEvents(){
  console.log("[pipeline] binding events");
  const runBtnEl=$("#runBtn"), stopBtnEl=$("#stopBtn"), browseBtnEl=$("#browseBtn"), fileInputEl=$("#fileInput");
  if(!runBtnEl||!browseBtnEl||!fileInputEl) console.error("[pipeline] missing buttons", {runBtnEl,browseBtnEl,fileInputEl});
  browseBtnEl?.addEventListener("click", e=>{ e.stopPropagation(); console.log("[pipeline] browse click"); fileInputEl.click(); });
  runBtnEl?.addEventListener("click", ()=>{ console.log("[pipeline] run click", pendingFiles); if(pendingFiles) uploadFiles(pendingFiles); else setStatus("Choose a file first", true); });
  stopBtnEl?.addEventListener("click", ()=>{ console.log("[pipeline] stop click"); if(abortCtrl) abortCtrl.abort(); setStatus("Stopping…"); });
  fileInputEl?.addEventListener("change", ()=>{ console.log("[pipeline] fileInput change", fileInputEl.files.length); setPendingFiles(fileInputEl.files); });
  const dz=$("#dropzone");
  dz?.addEventListener("click",e=>{ if(e.target.closest("button")||e.target.closest("label")||e.target.closest("select")) return; if(e.target===dz||e.target.closest(".dz-main")) fileInputEl.click(); });
  dz?.addEventListener("dragover",e=>{e.preventDefault(); dz.classList.add("drag");});
  dz?.addEventListener("dragleave",()=>dz.classList.remove("drag"));
  dz?.addEventListener("drop",e=>{e.preventDefault(); dz.classList.remove("drag"); console.log("[pipeline] drop", e.dataTransfer.files.length); setPendingFiles(e.dataTransfer.files);});
  $("#viewSel")?.addEventListener("change",updateViewMode);
  $("#playBoth")?.addEventListener("click", ()=>{ /* handled in wireSync, keep for init */ });
  srcVideo?.addEventListener("loadedmetadata",()=>{ $("#timeLabel").textContent=`0.00s / ${srcVideo.duration.toFixed(2)}s`; });
  $("#speedSel")?.addEventListener("change", e=>{ if(srcVideo) srcVideo.playbackRate = parseFloat(e.target.value)||1; });
  checkHealth(); updateViewMode();
  // boot the VRM avatar pane (loads the model into rest pose; fed once a stream arrives)
  createVrmRenderer(vrmHost).then(i=>{ vrmInst=i; if(currentStream&&i) i.setStream(currentStream); }).catch(e=>console.error("[vrm] init failed", e));
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", bindEvents);
else bindEvents();

// ============================================================================
// VRM avatar renderer — ports frontend/skeleton/VrmRenderer.ts to vanilla JS.
// Consumes the SAME view-normalised stream the skeleton panes use and retargets
// joint positions onto the signing VRM via forward-kinematic swing extraction.
// ============================================================================
async function createVrmRenderer(host){
  if(vrmInst) return vrmInst;
  let THREE, OrbitControls, GLTFLoader, VRMMOD;
  try{
    THREE = await import("three");
    ({OrbitControls} = await import("three/addons/controls/OrbitControls.js"));
    ({GLTFLoader} = await import("three/addons/loaders/GLTFLoader.js"));
    VRMMOD = await import("@pixiv/three-vrm");
  }catch(e){
    console.error("[vrm] import failed", e);
    host.innerHTML = '<div class="empty">VRM libs failed to load.<br><small>'+String(e)+'</small></div>';
    return null;
  }
  const { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName:V } = VRMMOD;

  const W = host.clientWidth||640, H = host.clientHeight||host.clientWidth||640;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, W/H, 0.1, 100);
  camera.position.set(0, 1.0, 3.0);
  const renderer = new THREE.WebGLRenderer({ antialias:true, alpha:true });
  renderer.setSize(W,H); renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.querySelector('#vrmEmpty')?.remove();
  host.appendChild(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.2));
  const dl = new THREE.DirectionalLight(0xffffff, 1.4); dl.position.set(1,2,2); scene.add(dl);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.9, 0); controls.enableDamping=true; controls.dampingFactor=0.08;
  controls.minDistance=1.2; controls.maxDistance=6; controls.update();
  new ResizeObserver(()=>{ const w=host.clientWidth||640, h=host.clientHeight||host.clientWidth||640; camera.aspect=w/h; camera.updateProjectionMatrix(); renderer.setSize(w,h); }).observe(host);

  const B = (Side,n)=> V[Side+n];
  function sideDrives(Side,p){
    return [
      {bone:B(Side,'UpperArm'),parent:V.Chest,restChild:B(Side,'LowerArm'),from:p+'Shoulder',to:p+'Elbow'},
      {bone:B(Side,'LowerArm'),parent:B(Side,'UpperArm'),restChild:B(Side,'Hand'),from:p+'Elbow',to:p+'Wrist'},
      {bone:B(Side,'Hand'),parent:B(Side,'LowerArm'),restChild:B(Side,'MiddleProximal'),from:p+'Hand',to:p+'Middle1'},
      {bone:B(Side,'ThumbProximal'),parent:B(Side,'Hand'),restChild:B(Side,'ThumbDistal'),from:p+'Thumb1',to:p+'Thumb2'},
      {bone:B(Side,'IndexProximal'),parent:B(Side,'Hand'),restChild:B(Side,'IndexIntermediate'),from:p+'Index1',to:p+'Index2'},
      {bone:B(Side,'IndexIntermediate'),parent:B(Side,'IndexProximal'),restChild:B(Side,'IndexDistal'),from:p+'Index2',to:p+'Index3'},
      {bone:B(Side,'IndexDistal'),parent:B(Side,'IndexIntermediate'),restChild:B(Side,'IndexDistal'),from:p+'Index3',to:p+'Index4',restFromParent:true},
      {bone:B(Side,'MiddleProximal'),parent:B(Side,'Hand'),restChild:B(Side,'MiddleIntermediate'),from:p+'Middle1',to:p+'Middle2'},
      {bone:B(Side,'MiddleIntermediate'),parent:B(Side,'MiddleProximal'),restChild:B(Side,'MiddleDistal'),from:p+'Middle2',to:p+'Middle3'},
      {bone:B(Side,'MiddleDistal'),parent:B(Side,'MiddleIntermediate'),restChild:B(Side,'MiddleDistal'),from:p+'Middle3',to:p+'Middle4',restFromParent:true},
      {bone:B(Side,'RingProximal'),parent:B(Side,'Hand'),restChild:B(Side,'RingIntermediate'),from:p+'Ring1',to:p+'Ring2'},
      {bone:B(Side,'RingIntermediate'),parent:B(Side,'RingProximal'),restChild:B(Side,'RingDistal'),from:p+'Ring2',to:p+'Ring3'},
      {bone:B(Side,'RingDistal'),parent:B(Side,'RingIntermediate'),restChild:B(Side,'RingDistal'),from:p+'Ring3',to:p+'Ring4',restFromParent:true},
      {bone:B(Side,'LittleProximal'),parent:B(Side,'Hand'),restChild:B(Side,'LittleIntermediate'),from:p+'Pinky1',to:p+'Pinky2'},
      {bone:B(Side,'LittleIntermediate'),parent:B(Side,'LittleProximal'),restChild:B(Side,'LittleDistal'),from:p+'Pinky2',to:p+'Pinky3'},
      {bone:B(Side,'LittleDistal'),parent:B(Side,'LittleIntermediate'),restChild:B(Side,'LittleDistal'),from:p+'Pinky3',to:p+'Pinky4',restFromParent:true},
      {bone:B(Side,'UpperLeg'),parent:V.Hips,restChild:B(Side,'LowerLeg'),from:p+'Hip',to:p+'Knee'},
      {bone:B(Side,'LowerLeg'),parent:B(Side,'UpperLeg'),restChild:B(Side,'Foot'),from:p+'Knee',to:p+'Ankle'},
    ];
  }
  const DRIVES = [
    {bone:V.Spine,parent:V.Hips,restChild:V.Chest,from:'spine',to:'chest'},
    {bone:V.Chest,parent:V.Spine,restChild:V.Neck,from:'chest',to:'neck'},
    {bone:V.Neck,parent:V.Chest,restChild:V.Head,from:'neck',to:'head'},
    ...sideDrives('Left','l'),
    ...sideDrives('Right','r'),
  ];
  const LEG_BONES = new Set([V.LeftUpperLeg,V.LeftLowerLeg,V.RightUpperLeg,V.RightLowerLeg]);

  let vrm=null, pendingJoints=null, streamRef=null;
  const restDir = new Map();
  const rootParentWorldQ = new THREE.Quaternion();
  const _c = new THREE.Vector3();

  function captureRest(v){
    const node = b=> v.humanoid.getNormalizedBoneNode(b);
    const wp = b=>{ const n=node(b); if(!n) return null; n.updateWorldMatrix(true,false); return n.getWorldPosition(new THREE.Vector3()); };
    for(const d of DRIVES){
      if(d.restFromParent){
        const self=wp(d.bone), par=wp(d.parent);
        if(self&&par&&self.distanceToSquared(par)>1e-8) restDir.set(d.bone, self.clone().sub(par).normalize());
        continue;
      }
      const a=wp(d.bone), b=wp(d.restChild);
      if(a&&b) restDir.set(d.bone, b.clone().sub(a).normalize());
    }
    node(V.Hips)?.parent?.getWorldQuaternion(rootParentWorldQ);
  }

  function applyPose(J){
    pendingJoints = J;
    if(!vrm) return;
    const pos = name=>{ const v=J[name]; return v ? new THREE.Vector3(v[0],v[1],v[2]) : null; };
    const pose={}, Rworld=new Map(), identity=new THREE.Quaternion();
    const hips=pos('hips'), chest=pos('chest'), lSh=pos('lShoulder'), rSh=pos('rShoulder');
    let Rhips=new THREE.Quaternion();
    if(hips&&chest&&lSh&&rSh){
      const up=chest.clone().sub(hips).normalize();
      const lr=rSh.clone().sub(lSh).normalize();
      const f=new THREE.Vector3().crossVectors(up,lr).normalize();
      const r=new THREE.Vector3().crossVectors(up,f).normalize();
      Rhips.setFromRotationMatrix(new THREE.Matrix4().makeBasis(r,up,f));
    }
    Rworld.set(V.Hips,Rhips);
    const hipsLocal=rootParentWorldQ.clone().invert().multiply(Rhips);
    pose[V.Hips]={rotation:[hipsLocal.x,hipsLocal.y,hipsLocal.z,hipsLocal.w]};
    for(const d of DRIVES){
      const Rparent=Rworld.get(d.parent)??identity;
      if(LEG_BONES.has(d.bone)){ Rworld.set(d.bone,Rparent); continue; }   // legs locked (bad depth)
      const rest=restDir.get(d.bone);
      const a=pos(d.from), b=pos(d.to);
      if(!rest||!a||!b){ Rworld.set(d.bone,Rparent); continue; }
      _c.copy(b).sub(a);
      if(_c.lengthSq()<1e-8){ Rworld.set(d.bone,Rparent); continue; }
      const obsLocal=_c.clone().applyQuaternion(Rparent.clone().invert()).normalize();
      const qLocal=new THREE.Quaternion().setFromUnitVectors(rest,obsLocal);
      pose[d.bone]={rotation:[qLocal.x,qLocal.y,qLocal.z,qLocal.w]};
      Rworld.set(d.bone,Rparent.clone().multiply(qLocal));
    }
    vrm.humanoid.setNormalizedPose(pose);
    vrm.humanoid.update();
  }

  const loader = new GLTFLoader();
  loader.register(p=> new VRMLoaderPlugin(p));
  loader.load('/models/AvatarSample_C.vrm', (gltf)=>{
    vrm = gltf.userData.vrm;
    try{ VRMUtils.removeUnnecessaryVertices(vrm.scene); }catch{}
    try{ VRMUtils.combineSkeletons(vrm.scene); }catch{}
    VRMUtils.rotateVRM0(vrm);
    scene.add(vrm.scene);
    captureRest(vrm);
    if(pendingJoints) applyPose(pendingJoints);
  }, undefined, (e)=>{ console.error('[vrm] load failed', e); host.innerHTML='<div class="empty">VRM load failed<br><small>'+String(e)+'</small></div>'; });

  function frameJoints(idx,alpha){
    if(!streamRef) return null;
    const fr=streamRef.frames, n=fr.length; if(!n) return null;
    const f0=fr[Math.max(0,Math.min(idx,n-1))], f1=fr[Math.max(0,Math.min(idx+1,n-1))];
    if(!f0) return null;
    if(!(alpha>0)||!f1) return f0.joints;
    const out={};
    for(const spec of streamRef.meta.joints){
      const a=f0.joints[spec.name], b=f1.joints[spec.name];
      if(!a&&!b) continue;
      if(!a||!b){ out[spec.name]=a||b; continue; }
      out[spec.name]=[a[0]*(1-alpha)+b[0]*alpha, a[1]*(1-alpha)+b[1]*alpha, a[2]*(1-alpha)+b[2]*alpha, Math.max(a[3],b[3])];
    }
    return out;
  }
  function setStream(s){ streamRef=s; setFrameLerp(0,0); }
  function setFrame(idx){ const j=frameJoints(idx,0); if(j) applyPose(j); }
  function setFrameLerp(idx,alpha){ const j=frameJoints(idx,alpha); if(j) applyPose(j); }

  (function loop(){ requestAnimationFrame(loop); controls.update(); if(vrm) vrm.update(1/60); renderer.render(scene,camera); })();

  vrmInst = { setStream, setFrame, setFrameLerp, get stream(){return streamRef}, set stream(s){ setStream(s); } };
  return vrmInst;
}
