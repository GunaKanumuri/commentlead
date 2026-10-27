const FEATURE_LABELS={
  'instagram-discovery':'Be first to hear about Instagram discovery.',
  'founder-discovery':'Find the people who need what you built.',
  'full-product':'A better way to find your people.',
  'matched-leads':'Find the right fit for your product.',
  'reply-drafts':'Start a more helpful conversation.',
  'saved-leads':'Keep your next opportunities together.',
  'automated-search':'Make room for easier discovery.'
};
let previewBusy=false,waitlistBusy=false;
let previewMode='topic';
const previewInputs={topic:'',video:''};
function setPreviewMode(mode){
  if(previewBusy)return;
  previewInputs[previewMode]=$('#landing-query').value;
  previewMode=mode==='video'?'video':'topic';
  const video=previewMode==='video',input=$('#landing-query');
  $('#search-topic').checked=!video;$('#search-video').checked=video;
  $('#topic-suggestions').hidden=video;
  input.value=previewInputs[previewMode];input.type=video?'url':'text';
  input.placeholder=video?'https://www.youtube.com/watch?v=…':'e.g. invoicing for freelancers';
  $('#query-label').textContent=video?'Which YouTube video should we read?':'What topic would your customers search for?';
  $('#query-help').textContent=video?'Paste a single YouTube video or Shorts link. We’ll assess its comments against your product.':'Enter a topic, not your product website. We’ll check up to 3 related YouTube videos and assess comments against your product.';
  $('#query-mark').textContent=video?'▶':'⌕';
  $('#preview-submit').textContent=video?'Find matches in video →':'Find opportunities →';
  $('#preview-error').textContent='';input.focus();
}
function chooseTopic(topic){
  if(previewBusy)return;
  setPreviewMode('topic');
  $('#landing-query').value=topic;
  $('#landing-query').focus();
}
function useBharatChitraExample(){
  if(previewBusy)return;
  $('#product-description').value='BharatChitra AI is a development prototype for creating short videos from ideas or scripts. AI script generation, image generation, Telugu voice narration and video assembly have been demonstrated in development. Telugu and Hindi audio have been tested locally.';
  $('#product-customer').value='YouTube Shorts creators, Telugu/Hindi storytellers, educators, faceless-channel owners and small businesses.';
  $('#product-readiness').value='prototype';
  $('#product-constraints').value='Development only; production end-to-end support and English remain unverified. No verified public prices: do not claim free or unlimited generation. Six visual styles, captions, thumbnails, hashtags, YouTube scheduling and AI Growth Coach are planned, not available. Exclude needs requiring guaranteed one-click publishing or fully automated production.';
  chooseTopic('AI short video creation Telugu Hindi narration');
}
function isYouTubeVideoLink(value){
  try{
    const url=new URL(value);
    if(!['https:','http:'].includes(url.protocol))return false;
    if(url.hostname==='youtu.be')return /^\/[\w-]{11}\/?$/.test(url.pathname);
    if(!['youtube.com','www.youtube.com','m.youtube.com'].includes(url.hostname))return false;
    return (url.pathname==='/watch'&&/^[\w-]{11}$/.test(url.searchParams.get('v')||''))||/^\/(shorts|embed)\/[\w-]{11}\/?$/.test(url.pathname);
  }catch{return false;}
}
function openWaitlist(interest='full-product'){
  $('#waitlist-interest').value=Object.hasOwn(FEATURE_LABELS,interest)?interest:'full-product';
  $('#waitlist-title').textContent=FEATURE_LABELS[$('#waitlist-interest').value];
  $('#waitlist-error').textContent='';$('#waitlist-form-panel').hidden=false;$('#waitlist-success').hidden=true;
  $('#waitlist-dialog').showModal();document.body.classList.add('modal-open');
}
function closeWaitlist(){if(waitlistBusy)return;$('#waitlist-dialog').close();}
async function submitWaitlist(){
  if(waitlistBusy)return;
  const email=$('#waitlist-email').value.trim();
  if(!email||!$('#waitlist-consent').checked){$('#waitlist-error').textContent='Enter your email and agree to receive a launch update.';return;}
  waitlistBusy=true;$('#waitlist-submit').disabled=true;$('#waitlist-submit').textContent='Adding you…';$('#waitlist-error').textContent='';
  try{
    const source=new URLSearchParams(window.location.search).get('utm_source')||'website';
    const result=await api('waitlist',{email,name:$('#waitlist-name').value.trim(),interest:$('#waitlist-interest').value,
      source:source.slice(0,100),consent:true,policy_version:POLICY_VERSION,website:$('#waitlist-website').value});
    if(!result.ok)throw new Error('Could not save your details. Please try again.');
    $('#waitlist-form-panel').hidden=true;$('#waitlist-success').hidden=false;$('#waitlist-done').focus();
    $('#waitlist-form').reset();
  }catch(error){$('#waitlist-error').textContent=error.message;}
  finally{waitlistBusy=false;$('#waitlist-submit').disabled=false;$('#waitlist-submit').textContent='Join the waitlist ↗';}
}
async function ensurePublicPolicies(){
  if(!$('#preview-policy').checked)throw new Error('Please read and agree to the Terms and Privacy Policy before previewing comments.');
  await api('legal/accept-public',{accepted:true,version:POLICY_VERSION});
}
function sourceDate(value){
  const date=new Date(value);return value&&!Number.isNaN(date.valueOf())?date.toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'}):'Date unavailable';
}
function youtubeLink(value){
  try{const url=new URL(value);return url.protocol==='https:'&&['www.youtube.com','youtube.com','youtu.be'].includes(url.hostname)?url.href:'https://www.youtube.com/';}
  catch{return 'https://www.youtube.com/';}
}
function matchEvidence(lead){
  const e=lead.evidence;if(!e||typeof e!=='object')return '';
  const unknowns=Array.isArray(e.unknowns)?e.unknowns:[];
  return `<dl class="match-evidence"><div><dt>Customer need</dt><dd>${esc(e.need)}</dd></div><div><dt>Evidence from their comment</dt><dd><q>${esc(e.quote)}</q></dd></div><div><dt>Your matching feature</dt><dd>${esc(e.feature)}</dd></div><div><dt>Why it could fit</dt><dd>${esc(e.reason)}</dd></div></dl><p class="match-unknowns"><b>Still unknown:</b> ${unknowns.map(esc).join(' · ')}</p>`;
}
function renderPreview(result){
  const leads=Array.isArray(result.leads)?result.leads:[];
  $('#preview-heading').textContent=leads.length?`${leads.length} potential ${result.readiness==='prototype'?'early-access conversation':'match'}${leads.length===1?'':'s'}`:result.partial?'Search incomplete':'No relevant opportunities found';
  const stats=result.stats||{};
  $('#preview-summary').textContent=`${Number(stats.videos_checked)||0} videos checked · ${Number(stats.comments_read)||0} comments read · ${Number(stats.comments_assessed)||0} assessed · ${leads.length} potential matches. ${result.message||''} ${result.scope||''}`;
  const video=result.video;
  const videos=Array.isArray(result.videos)?result.videos:video?[video]:[];
  $('#preview-video-card').innerHTML=videos.map(item=>`<div class="video-banner"><div><h3>${esc(item.title)}</h3><p>${esc(item.channel||'YouTube')} · Source: YouTube Data API</p></div><a class="source-link" href="${esc(youtubeLink(item.video_url))}" target="_blank" rel="noopener noreferrer">Open video ↗</a></div>`).join('');
  $('#preview-leads-list').innerHTML=leads.map(lead=>`<article class="comment-card"><div class="comment-top"><span class="avatar clay" aria-hidden="true">${esc((lead.author||'Y').replace(/^@/,'').slice(0,1).toUpperCase())}</span><b>${esc(lead.author||'YouTube commenter')}</b><time>${esc(sourceDate(lead.published_at))}</time></div><p>${esc(lead.text)}</p>${matchEvidence(lead)}<div class="comment-bottom"><span class="tag">${esc(lead.intent||'Buying intent unverified')}</span><a class="source-link" href="${esc(youtubeLink(lead.link))}" target="_blank" rel="noopener noreferrer">View original comment ↗</a></div></article>`).join('');
}
async function runFreePreview(){
  if(previewBusy)return;
  const query=$('#landing-query').value.trim();if(!query)return;
  if(previewMode==='video'&&!isYouTubeVideoLink(query)){$('#preview-error').textContent='Paste a YouTube video link, such as https://www.youtube.com/watch?v=VIDEO_ID. Channel and website links are not supported here.';return;}
  if(previewMode==='topic'&&/^(https?:\/\/|www\.)/i.test(query)){$('#preview-error').textContent='Enter a topic here, such as invoicing for freelancers. To paste a video link, choose “I have a YouTube video link”.';return;}
  const product={description:$('#product-description').value.trim(),customer:$('#product-customer').value.trim(),constraints:$('#product-constraints').value.trim(),readiness:$('#product-readiness').value};
  if(product.description.length<15||product.customer.length<3){$('#preview-error').textContent='Describe the features that work today and who your product is for. We need this to assess real relevance.';return;}
  $('#search-topic').disabled=true;$('#search-video').disabled=true;
  previewBusy=true;$('#preview-submit').disabled=true;$('#preview-submit').textContent='Reading comments…';$('#preview-error').textContent='';
  $('#preview-video-card').innerHTML='';$('#preview-leads-list').innerHTML='';$('#preview-summary').textContent='';$('#preview-results').hidden=true;
  try{const result=await api('free-preview',{query,mode:previewMode,product});renderPreview(result);$('#preview-results').hidden=false;$('#preview-results').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}
  catch(error){$('#preview-error').textContent=error.message;}
  finally{previewBusy=false;$('#search-topic').disabled=false;$('#search-video').disabled=false;$('#preview-submit').disabled=false;$('#preview-submit').textContent=previewMode==='video'?'Find matches in video →':'Find opportunities →';}
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-waitlist]');if(button)openWaitlist(button.dataset.waitlist);
  const topic=event.target.closest('[data-topic]');if(topic)chooseTopic(topic.dataset.topic);
});
$('#preview-form').addEventListener('submit',event=>{event.preventDefault();runFreePreview();});
$('#search-topic').addEventListener('change',()=>setPreviewMode('topic'));
$('#search-video').addEventListener('change',()=>setPreviewMode('video'));
$('#bharatchitra-example').addEventListener('click',useBharatChitraExample);
$('#waitlist-form').addEventListener('submit',event=>{event.preventDefault();submitWaitlist();});
$('#waitlist-close').addEventListener('click',closeWaitlist);
$('#waitlist-done').addEventListener('click',closeWaitlist);
$('#waitlist-dialog').addEventListener('cancel',event=>{if(waitlistBusy)event.preventDefault();});
$('#waitlist-dialog').addEventListener('close',()=>document.body.classList.remove('modal-open'));
