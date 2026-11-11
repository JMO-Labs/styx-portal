(function(){
var pcs=[],RP=window.RTCPeerConnection;
if(RP){window.RTCPeerConnection=class extends RP{constructor(){super(...arguments);pcs.push(this)}}}
async function webrtc(){
for(var pc of pcs){try{var st=await pc.getStats(),cur=null,by={};
st.forEach(function(r){by[r.id]=r;if(r.type==='transport'&&r.selectedCandidatePairId)cur=r.selectedCandidatePairId});
var p=cur&&by[cur];if(p&&typeof p.currentRoundTripTime==='number')return p.currentRoundTripTime*1000}catch(e){}}
return null}
function ws(){var s=window.system_stats||window.webrtcStats||{};return typeof s.rtt_ms==='number'?s.rtt_ms:null}
async function tick(){
if(document.visibilityState==='hidden'||window.parent===window)return;
var ms=await webrtc(),t='webrtc';
if(ms===null){ms=ws();t='websocket'}
if(typeof ms!=='number'||!isFinite(ms)||ms<0)return;
try{window.parent.postMessage({type:'styx-rtt',rtt_ms:ms,transport:t},location.origin)}catch(e){}}
setInterval(tick,5000);
})();
