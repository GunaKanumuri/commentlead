// ---------- Top-Level Screen Router ----------
function showScreen(name) {
  if (name==='pricing') renderPricing();
  if (name === 'app' && !getToken()) { openAuthScreen('login'); return; }
  ['landing', 'preview', 'auth', 'pricing', 'app'].forEach(s => {
    const el = $('#screen-' + s);
    if (el) el.hidden = (s !== name);
  });
  $('#mob-nav').hidden = (name !== 'app');
  window.scrollTo(0, 0);
}

function openAppDashboard() {
  if (!getToken()) { openAuthScreen('login'); return; }
  if (!workspacesList.length) { newProduct(true); return; }
  showScreen('app');
  switchAppView('dashboard');
}

function switchAppView(view) {
  showScreen('app');
  ['dashboard', 'finder', 'reports', 'workspaces', 'settings'].forEach(v => {
    const sec = $('#view-' + v);
    if (sec) sec.hidden = (v !== view);
    const btn = $('#nav-' + v);
    if (btn) btn.className = 'side-btn' + (v === view ? ' active' : '');
    const mbtn = $('#mnav-' + v);
    if (mbtn) mbtn.className = 'mob-nav-btn' + (v === view ? ' active' : '');
  });
}

function switchDashTab(which) {
  $('#dtab-leads').className = 'sub-tab-btn' + (which === 'leads' ? ' active' : '');
  $('#dtab-reports').className = 'sub-tab-btn' + (which === 'reports' ? ' active' : '');
  if (which === 'reports') switchAppView('reports');
}

function switchFinderMode(mode) {
  $('#ftab-kw').className = 'sub-tab-btn' + (mode === 'kw' ? ' active' : '');
  $('#ftab-url').className = 'sub-tab-btn' + (mode === 'url' ? ' active' : '');
  $('#finder-kw-pane').hidden = (mode !== 'kw');
  $('#finder-url-pane').hidden = (mode !== 'url');
}

function openFilteredLeads(statusVal) {
  switchAppView('finder');
  $('#status-filter').value = statusVal;
  loadLeads();
}

// ---------- Screen 2: Free Search Preview (No Login) ----------
function intentBadgeClass(intent) {
  const s = String(intent || '').toLowerCase();
  if (s.includes('alternative')) return 'i-alt';
  if (s.includes('question')) return 'i-ask';
  if (s.includes('free')) return 'i-free';
  if (s.includes('price') || s.includes('concern')) return 'i-price';
  return 'i-high';
}

function inferIntentFromLead(x) {
  const txt = ((x.text || '') + ' ' + (x.reason || '')).toLowerCase();
  if (txt.includes('alternative') || txt.includes('competitor') || txt.includes('instead') || txt.includes('emoha') || txt.includes('capcut') || txt.includes('invideo') || txt.includes('flow')) return ['Looking for alternative', 'i-alt'];
  if (txt.includes('price') || txt.includes('cost') || txt.includes('paid') || txt.includes('upgrade') || txt.includes('subscription') || txt.includes('tariff')) return ['Price concern', 'i-price'];
  if (txt.includes('free') || txt.includes('credit')) return ['Looking for free option', 'i-free'];
  if ((x.text || '').includes('?') || txt.includes('how') || txt.includes('which') || txt.includes('suggest') || txt.includes('link')) return ['Asking a question', 'i-ask'];
  return [x.score >= 80 ? 'High intent' : 'Potential buyer', 'i-high'];
}

async function runFreePreview(qOverride) {
  const q = (qOverride || $('#landing-query').value || 'best productivity apps 2026').trim();
  $('#preview-query').value = q;
  showScreen('preview');
  $('#preview-heading').textContent = 'Searching YouTube comments…';
  $('#preview-video-card').innerHTML = `<div style="color:var(--mute);padding:8px">⏳ Fetching real video & comments for <b>${esc(q)}</b>…</div>`;
  $('#preview-leads-list').innerHTML = '';
  try {
    const d = await api('free-preview', {query: q});
    const v = d.video || {};
    const leads = d.leads || [];
    $('#preview-heading').textContent = `${leads.length} real comment${leads.length === 1 ? '' : 's'} · not yet qualified`;
    if (!d.video) { $('#preview-video-card').textContent = d.message || 'No matching videos found.'; return; }
    $('#preview-video-card').innerHTML = `
      <div class="video-banner-left">
        <div class="video-thumb-wrap">
          <img src="${esc(v.thumbnail)}" alt="Video thumbnail">

        </div>
        <div>
          <div style="font-weight:800;font-size:15px">${esc(v.title)}</div>
          <div style="font-size:13px;color:var(--mute);margin-top:2px">
            <a href="${esc(v.channel_url || v.video_url)}" target="_blank" rel="noopener" style="font-weight:600;text-decoration:underline">${esc(v.channel)}</a> · ${esc(v.meta || 'Source: YouTube Data API')}
          </div>
        </div>
      </div>
      <a class="btn-outline" href="${esc(v.video_url)}" target="_blank" rel="noopener">View on YouTube ↗</a>
    `;
    const avColors = ['', 'a2', 'a3', 'a4'];
    $('#preview-leads-list').innerHTML = leads.map((l, idx) => {
      const init = (l.author || 'U').replace(/^@/, '').slice(0, 1).toUpperCase();
      const icls = intentBadgeClass(l.intent);
      return `<div class="lead-split-card">
        <div>
          <div style="display:flex;gap:11px;align-items:flex-start">
            <div class="avatar ${avColors[idx % avColors.length]}">${esc(init)}</div>
            <div style="flex:1">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <b style="font-size:14px">${esc(l.author)}</b>
                <span style="font-size:12px;color:var(--mute)">${esc(sourceDate(l.published_at))}</span>
                <a href="${esc(l.link)}" target="_blank" rel="noopener" style="font-size:12px;color:var(--brown);font-weight:700;margin-left:auto">Open comment ↗</a>
              </div>
              <p style="margin:6px 0 10px;color:var(--ink);font-size:14px">${esc(l.text)}</p>
              <span class="intent-pill ${icls}">${esc(l.intent)}</span>
            </div>
          </div>
        </div>
        <div class="reply-pane"><b>Source preview</b><p>Create a product profile to assess whether this person needs what you offer. No buying intent or product recommendation has been verified.</p></div>
      </div>`;
    }).join('') || `<p>${esc(d.message || 'No usable comments were returned.')}</p>`;
  } catch (e) {
    $('#preview-heading').textContent = 'Could not load preview';
    $('#preview-video-card').innerHTML = `<div style="color:var(--rose)">${esc(e.message)}</div>`;
  }
}

// Offers come from the same catalog as backend enforcement.
async function renderPricing() {
  const target=$('#pricing-cards');
  try {
    const catalog=await api('pricing');
    target.innerHTML=catalog.plans.map(plan=>`<div class="price-card"><div><h2>${esc(plan.label)}</h2>
      <div class="price-amount">₹${plan.price_minor/100}<span>${plan.key==='free' ? ' / one-time trial' : ' / month'}</span></div>
      <ul class="price-features"><li>Up to ${plan.leads.toLocaleString()} matched opportunities${plan.key==='free' ? ' in 7 days' : ' per billing month'}</li>
      <li>${plan.products} product${plan.products>1 ? 's sharing the allowance' : ''}</li><li>Up to ${plan.analysis.toLocaleString()} comments analysed</li>
      <li>${plan.searches} discovery runs${plan.key==='free' ? ' total' : ' per month'}</li><li>Evidence, reply drafts and outcome tracking</li>
      <li>${plan.auto_scan ? 'Weekly scheduling uses the included runs' : 'Manual discovery on demand'}</li></ul></div>
      <button class="${plan.key==='free' ? 'btn-outline' : 'btn-brown'}" onclick="${plan.key==='free' ? 'openAppDashboard()' : `choosePlan('${plan.key}',${catalog.checkout_enabled})`}">${plan.key==='free' ? 'Try your product' : catalog.checkout_enabled ? 'Choose '+esc(plan.label) : 'Join launch list'}</button></div>`).join('');
  } catch(e) {target.textContent='Could not load prices: '+e.message;}
}
async function choosePlan(key,enabled) {
  if (!getToken()) {openAuthScreen('register');return;}
  if (!enabled) {await wantUpgrade(key);return;}
  try { const result=await api('billing/checkout',{plan:key}); window.location.assign(result.checkout_url); }
  catch(e) {alert(e.message);}
}
async function ensurePublicPolicies() {
  if (!$('#preview-policy').checked) throw new Error('Read the Terms and Privacy Policy, then tick the agreement checkbox before previewing.');
  const response=await fetch(apiUrl('legal/accept-public'),{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:POLICY_VERSION,accepted:true})});
  if (!response.ok) throw new Error('Could not record policy acceptance. Please retry.');
}
async function ensurePolicies() {
  if (policiesAccepted) return;
  const status=await api('legal/status');
  if (status.accepted) {policiesAccepted=true;$('#policy-consent').hidden=true;return;}
  if (!$('#account-policy').checked && !$('#auth-policy').checked) throw new Error('Read and accept the Terms and Privacy Policy using the checkbox above.');
  await api('legal/accept',{version:POLICY_VERSION,accepted:true});
  policiesAccepted=true;$('#policy-consent').hidden=true;
}
async function acceptPolicies() {
  try {await ensurePolicies();$('#policy-message').textContent='Saved';}
  catch(e) {$('#policy-message').textContent=e.message;}
}
async function cancelSubscription() {
  try {const result=await api('billing/cancel',{});$('#billing-message').textContent=result.message;await loadPlan();}
  catch(e) {$('#billing-message').textContent=e.message;}
}
async function deleteMyAccount() {
  try {const result=await api('account/delete',{confirmation:$('#delete-confirmation').value});$('#delete-message').textContent=result.message;await logout();}
  catch(e) {$('#delete-message').textContent=e.message;}
}

// ---------- Workspaces & 1-Question-at-a-Time Setup Wizard ----------
let workspacesList = [];
async function loadWs(selectedId) {
  const all = await api('workspaces');
  workspacesList = all.filter(w => (w.pitch || '').trim().length > 10);
  if (!workspacesList.length) {
    showScreen('app');
    newProduct(true);
    return;
  }
  $('#ws').innerHTML = workspacesList.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('');
  if (selectedId) $('#ws').value = selectedId;
  onWsChange();
  loadAutomationStatus();
}
function curWs() { return workspacesList.find(x => x.id == $('#ws').value) || workspacesList[0]; }
function onWsChange() {
  const c = curWs();
  if (!c) return;
  $('#ws-sub').textContent = (c.pitch || '').slice(0, 48) + '…';
  $('#dash-pname-btn').textContent = c.name;
  const pi = document.getElementById(' pname-inline');
  if (pi) pi.textContent = c.name;
  $('#ppitch').textContent = (c.pitch || '').length > 140 ? c.pitch.slice(0, 140) + '…' : c.pitch;
  $('#bl').value = c.blocklist || '';
  loadLeads();
}

const BIZ_TYPES = [
  '📱 App / Website / SaaS Startup',
  '🏠 Homemade / D2C / Small Business',
  '🎥 YouTuber / Creator / Coach / Service'
];
let wiz = {profile:{}, step:0, biz_type:BIZ_TYPES[0], name:'', site_url:'', about:'', features:'', audience:'', pitch:'', feat_list:[], keywords:'', q:'', site:false, edit:false};

function newProduct(first) {
  wiz = {profile:{}, step:0, biz_type:BIZ_TYPES[0], name:'', site_url:'', about:'', features:'', audience:'', pitch:'', feat_list:[], keywords:'', q:'', site:false, edit:false, first:!!first};
  switchAppView('workspaces');
  renderWizard();
}
function editProduct() {
  const c = curWs();
  if (!c) return newProduct(false);
  const kws = (c.signals || '').split(/;\s*|\n/).map(x => x.trim()).filter(Boolean);
  wiz = {profile:c.profile || {}, step:4, biz_type:(c.profile || {}).business_type || BIZ_TYPES[0], name:c.name, site_url:(c.profile || {}).website || '', about:c.pitch, features:'', audience:(c.profile || {}).target_customer || '', pitch:c.pitch, feat_list:[], keywords:kws.join('\n'), q:'', site:false, edit:true};
  switchAppView('workspaces');
  renderWizard();
}
function selectBizType(idx) { wiz.biz_type = BIZ_TYPES[idx]; renderWizard(); }
function addAudChip(txt) {
  const el = $('#ans-aud');
  if (!el) return;
  const cur = el.value.trim();
  if (!cur.toLowerCase().includes(txt.toLowerCase())) el.value = cur ? (cur + ', ' + txt) : txt;
  el.focus();
}

function matchingFields() {
  const p = wiz.profile || {};
  const homemade = wiz.biz_type.includes('Homemade');
  const field = (key, label, hint, required=false) => `<label class="field-label" for="match-${key}">${label}${required ? ' *' : ' (optional)'}</label><textarea id="match-${key}" class="field-input" rows="2" maxlength="${({target_customer:1000,problem:1500,locations:500,languages:300,pricing:500})[key] || 1000}" placeholder="${esc(hint)}">${esc(p[key] || '')}</textarea>`;
  return `<p style="color:var(--mute)">Required fields help us find people you can actually serve. Leave optional details blank when unknown.</p>
    ${field('target_customer', 'Who is your ideal buyer?', homemade ? 'Families buying homemade pickles; retail buyers, not resellers' : 'Solo SaaS founders struggling to find their first customers', true)}
    ${field('problem', 'What customer problem do you solve?', homemade ? 'Need fresh homemade pickles without added preservatives' : 'Finding people asking for a cheaper, simpler customer-support tool', true)}
    <label class="field-label" for="match-delivery_scope">Where can you sell or deliver? *</label>
    <select id="match-delivery_scope" class="field-input">
      <option value="">Choose your service area</option>
      <option value="global" ${p.delivery_scope === 'global' ? 'selected' : ''}>Worldwide / online</option>
      <option value="countries" ${p.delivery_scope === 'countries' ? 'selected' : ''}>Specific countries / nationwide delivery</option>
      <option value="local" ${p.delivery_scope === 'local' ? 'selected' : ''}>Specific cities / local delivery</option>
    </select>
    ${field('locations', 'Countries, cities or delivery area', homemade ? 'Hyderabad only, within 10 km of Kukatpally' : 'India, US and UK; or worldwide', true)}
    ${field('languages', 'Languages your buyers use', 'English, Hindi, Hinglish, Telugu — include only languages you can support', true)}
    <details style="margin-top:16px"><summary style="cursor:pointer;font-weight:700">Improve matching further: price, alternatives and limits</summary>
      ${field('pricing', 'Price and payment terms', homemade ? '₹250 per 500g jar; delivery ₹50; minimum order 2 jars' : '₹499/month or $9/month; 7-day trial; no free plan')}
      ${field('competitors', 'Alternatives customers compare you with', 'Known competitor names, separated by commas; leave blank if unsure')}
      ${field('exclusions', 'Who should we exclude?', homemade ? 'Wholesale enquiries, resellers, job seekers' : 'Job seekers, students wanting free homework help, enterprise procurement')}
      ${field('limitations', 'What can you NOT offer?', homemade ? 'No international shipping; 2-day preparation time; contains peanuts' : 'No mobile app, no Instagram integration; English support only')}
    </details>`;
}
function readMatchingProfile() {
  const p = {business_type:wiz.biz_type, website:wiz.site_url || ''};
  for (const key of ['target_customer','problem','delivery_scope','locations','languages','pricing','competitors','exclusions','limitations']) {
    p[key] = $('#match-' + key).value.trim();
  }
  wiz.profile = p;
  wiz.audience = p.target_customer;
  const required = [['target_customer',3,'Describe your ideal buyer.'],['problem',5,'Describe the problem you solve.'],['delivery_scope',1,'Choose where you can serve buyers.'],['locations',2,'Enter your service area, or worldwide.'],['languages',2,'Enter the languages you support.']];
  for (const [key, min, message] of required) {
    if (p[key].length < min) { $('#werr').textContent = message; $('#match-' + key).focus(); return false; }
  }
  return true;
}

function renderWizard() {
  $('#prog').innerHTML = [0,1,2,3,4].map(i => `<i class="${i <= wiz.step ? 'on' : ''}"></i>`).join('');
  const w = $('#wizbody');
  const cancel = workspacesList.length ? `<button class="btn-outline" onclick="switchAppView('dashboard')">Cancel</button>` : '';
  if (wiz.step === 0) {
    w.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--brown);text-transform:uppercase">Question 1 of 4 · Your Business</div>
      <h2 class="serif" style="font-size:28px;margin:6px 0">What is your business, app, or channel called?</h2>
      <p style="color:var(--mute);margin:0 0 12px">Select your business type and enter your brand or product name.</p>
      <div class="chips">${BIZ_TYPES.map((t, idx) => `<button type="button" class="chip ${wiz.biz_type === t ? 'on' : ''}" onclick="selectBizType(${idx})">${esc(t)}</button>`).join('')}</div>
      <input id="ans" class="field-input" placeholder="e.g. AYANA, BharatChitra AI, Meera Homemade Pickles">
      <div id="werr" style="color:var(--rose);font-size:13px;font-weight:600;min-height:20px;margin-top:6px"></div>
      <div style="display:flex;gap:10px;margin-top:16px"><button class="btn-brown" onclick="wizNext()">Next →</button>${cancel}</div>`;
    const a = $('#ans'); a.value = wiz.name; a.focus();
    a.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); wizNext(); } };
  } else if (wiz.step === 1) {
    w.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--brown);text-transform:uppercase">Question 2 of 4 · Website / README or 1-Line Summary</div>
      <h2 class="serif" style="font-size:28px;margin:6px 0">What does ${esc(wiz.name)} do?</h2>
      <p style="color:var(--mute);margin:0 0 12px">Paste your <b>Website or GitHub README link</b> so our bot extracts all features automatically, or write 1 simple line.</p>
      <label class="field-label">Website or GitHub README URL (optional)</label>
      <input id="ans-site" class="field-input" placeholder="https://yourwebsite.com or https://github.com/user/repo">
      <label class="field-label">Or describe what you sell in 1 line</label>
      <textarea id="ans" class="field-input" rows="3" placeholder="e.g. WhatsApp companion for elderly parents in India"></textarea>
      <div id="werr" style="color:var(--rose);font-size:13px;font-weight:600;min-height:20px;margin-top:6px"></div>
      <div style="display:flex;gap:10px;margin-top:16px"><button class="btn-brown" onclick="wizNext()">Next →</button><button class="btn-outline" onclick="wizBack()">← Back</button>${cancel}</div>`;
    $('#ans-site').value = wiz.site_url; $('#ans').value = wiz.about; $('#ans').focus();
  } else if (wiz.step === 2) {
    w.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--brown);text-transform:uppercase">Question 3 of 4 · Key Features / Offerings</div>
      <h2 class="serif" style="font-size:28px;margin:6px 0">What are the 3–4 main features of ${esc(wiz.name)}?</h2>
      <p style="color:var(--mute);margin:0 0 12px">List what you actually offer. We match customer needs to these features and your service limits.</p>
      <textarea id="ans" class="field-input" rows="4" placeholder="1. Daily safety check-ins&#10;2. Medicine reminders on WhatsApp&#10;3. Daily activities tracking&#10;4. Emergency keyword alerts"></textarea>
      <div id="werr" style="color:var(--rose);font-size:13px;font-weight:600;min-height:20px;margin-top:6px"></div>
      <div style="display:flex;gap:10px;margin-top:16px"><button class="btn-brown" onclick="wizNext()">Next →</button><button class="btn-outline" onclick="wizBack()">← Back</button>${cancel}</div>`;
    const a = $('#ans'); a.value = wiz.features; a.focus();
  } else if (wiz.step === 3) {
    w.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--brown);text-transform:uppercase">Question 4 of 4 · Customer Match</div>
      <h2 class="serif" style="font-size:28px;margin:6px 0">Who can ${esc(wiz.name)} help?</h2>
      ${matchingFields()}
      <div id="werr" style="color:var(--rose);font-size:13px;min-height:20px;margin-top:6px"></div>
      <div style="display:flex;gap:10px;margin-top:16px"><button class="btn-brown" onclick="wizNext()">Generate Profile & Keywords</button><button class="btn-outline" onclick="wizBack()">← Back</button>${cancel}</div>`;
  } else {
    const featsHtml = wiz.feat_list && wiz.feat_list.length ? `<div class="chips">${wiz.feat_list.map(f => `<span class="chip on">✓ ${esc(f)}</span>`).join('')}</div>` : '';
    w.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--green);text-transform:uppercase">✓ Profile Ready</div>
      <h2 class="serif" style="font-size:26px;margin:6px 0">Review ${esc(wiz.name)}'s Profile & Search Keywords</h2>
      ${wiz.site ? '<p style="color:var(--green);font-weight:700;font-size:13px">✓ Extracted from your website / README</p>' : ''}
      ${featsHtml}
      <details style="margin:16px 0" open><summary style="cursor:pointer;font-weight:700">Your customer matching criteria</summary>${matchingFields()}</details>
      <label class="field-label">Company Description & Main Features</label>
      <textarea id="rp" class="field-input" rows="4"></textarea>
      <label class="field-label">Search & Match Keywords (one per line)</label>
      <textarea id="rk" class="field-input" rows="6"></textarea>
      <div id="werr" style="color:var(--rose);font-size:13px;font-weight:600;min-height:20px;margin-top:6px"></div>
      <div style="display:flex;gap:10px;margin-top:16px;flex-wrap:wrap">
        <button class="btn-brown" id="savebtn" onclick="wizFinish()">Save & Find Leads →</button>
        <button class="btn-outline" onclick="wiz.step=0;renderWizard()">🧙 Restart Step-by-Step Questions</button>
        ${cancel}
      </div>`;
    $('#rp').value = wiz.pitch;
    $('#rk').value = wiz.keywords;
  }
}
function wizBack() { if (wiz.step === 3) readMatchingProfile(); wiz.step = Math.max(0, wiz.step - 1); renderWizard(); }
async function wizNext() {
  if (wiz.step === 0) {
    wiz.name = $('#ans').value.trim();
    if (!wiz.name) { $('#werr').textContent = 'Please enter your name.'; return; }
    wiz.step = 1; renderWizard(); return;
  }
  if (wiz.step === 1) {
    wiz.site_url = $('#ans-site').value.trim();
    wiz.about = $('#ans').value.trim();
    if (!wiz.site_url && wiz.about.length < 5) { $('#werr').textContent = 'Please paste a link or write 1 line.'; return; }
    wiz.step = 2; renderWizard(); return;
  }
  if (wiz.step === 2) {
    wiz.features = $('#ans').value.trim();
    if (!wiz.site_url && (wiz.about.length + wiz.features.length) < 8) { $('#werr').textContent = 'Please add your main features.'; return; }
    wiz.step = 3; renderWizard(); return;
  }
  if (wiz.step === 3) {
    if (!readMatchingProfile()) return;
    wiz.step = 4;
    $('#wizbody').innerHTML = `<div style="padding:24px;text-align:center"><h3 class="serif">Our AI is building ${esc(wiz.name)}'s profile & keywords…</h3><p style="color:var(--mute)">Takes ~8 seconds.</p></div>`;
    try {
      const combinedAbout = [wiz.site_url, wiz.about].filter(Boolean).join(' ');
      const d = await api('onboard/suggest', {name:wiz.name, biz_type:wiz.biz_type, about:combinedAbout, features:wiz.features, audience:wiz.audience, profile:wiz.profile});
      wiz.pitch = d.pitch;
      wiz.feat_list = d.features || [];
      wiz.keywords = (d.keywords || []).join('\n');
      wiz.q = d.question || '';
      wiz.site = !!d.read_website;
      renderWizard();
    } catch (e) {
      wiz.step = 3; renderWizard(); $('#werr').textContent = e.message;
    }
  }
}
async function wizFinish() {
  if (!readMatchingProfile()) return;
  const pitch = $('#rp').value.trim(), kws = $('#rk').value.split('\n').map(x => x.trim()).filter(Boolean);
  if (pitch.length < 10) { $('#werr').textContent = 'Description is too short.'; return; }
  $('#savebtn').disabled = true;
  try {
    const res = await api('workspaces', {name:wiz.name, pitch, profile:wiz.profile, signals:kws.join('; '), blocklist:(curWs() && wiz.edit) ? curWs().blocklist || '' : ''});
    await loadWs(res.id);
    switchAppView('finder');
    if (!wiz.edit) auto();
  } catch (e) {
    $('#werr').textContent = e.message;
    $('#savebtn').disabled = false;
  }
}

// ---------- Finding Leads & Polling ----------
let pollTimer = null, searching = false, interestSent = false, planInfo = null;
function box(cls, html) { $('#st').innerHTML = html ? `<div class="status-box ${cls}">${html}</div>` : ''; }

function startPolling(jid) {
  if (pollTimer) clearInterval(pollTimer);
  searching = true;
  $('#findbtn').disabled = true;
  box('run', '⏳ Starting YouTube search & comment analysis…');
  pollTimer = setInterval(async () => {
    try {
      const j = await api('job/' + jid);
      if (j.error) {
        clearInterval(pollTimer); searching = false; loadPlan();
        box('bad', '<b>Error:</b> ' + esc(j.error));
        return;
      }
      if (j.done) {
        clearInterval(pollTimer); searching = false; loadPlan();
        box('good', '<b>✓ Done.</b> ' + esc(j.msg) + (j.result && j.result.queries && j.result.queries.length ? `<div style="font-size:12px;margin-top:4px;opacity:0.85">Queries searched: ${j.result.queries.map(esc).join(' · ')}</div>` : ''));
        loadLeads(); loadAutomationStatus();
      } else {
        box('run', `⏳ <b>${esc(j.msg || 'Working…')}</b>${j.progress ? ` (${j.progress}%)` : ''}`);
      }
    } catch (e) {
      clearInterval(pollTimer); searching = false; loadPlan();
      box('bad', 'Connection error: ' + esc(e.message));
    }
  }, 2500);
}

async function auto() {
  if (!$('#ws').value) return;
  box('run', '⏳ Starting your lead search…');
  try {
    const r = await api('auto', {workspace_id: +$('#ws').value, per_video: 80, max_videos: 12});
    startPolling(r.job_id);
  } catch (e) { box('bad', esc(e.message)); }
}

async function scan() {
  if (!$('#ws').value) return;
  const urls = $('#urls').value.split('\n').map(u => u.trim()).filter(Boolean);
  if (!urls.length) return alert('Please paste at least one YouTube link');
  box('run', '⏳ Scanning specified videos…');
  try {
    const r = await api('scan', {workspace_id: +$('#ws').value, urls, per_video: +$('#pv').value || 80});
    startPolling(r.job_id);
  } catch (e) { box('bad', esc(e.message)); }
}

// ---------- Rendering Dashboard Table (Screen 5) & Lead Finder Cards (Screen 6) ----------
async function loadLeads() {
  await loadPlan();
  if (!$('#ws').value) return;
  const min = $('#level').value || '60';
  const status = $('#status-filter').value || 'new';
  const all = await api(`leads?workspace_id=${$('#ws').value}&min_score=${min}&status=${status}`);
  await loadWorkspaceMetrics();
  const showBad = $('#show-bad').checked;
  const l = showBad ? all : all.filter(x => x.feedback !== 'bad');
  const openLeads = l.filter(x => !x.locked);
  const lockedLeads = l.filter(x => x.locked);
  const strongCount = openLeads.filter(x => !x.analysis_stale && x.score >= 80).length;

  // Update KPI Cards on Screen 5
  $('#kpi-leads').textContent = openLeads.length;
  $('#kpi-strong').textContent = strongCount;
  const pctIntent = openLeads.length ? Math.round((strongCount / openLeads.length) * 100) : null;
  $('#kpi-intent').textContent = pctIntent == null ? '—' : pctIntent + '%';

  // Render Dashboard Table (Screen 5)
  const avColors = ['', 'a2', 'a3', 'a4'];
  if (!openLeads.length) {
    $('#dash-table-body').innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--mute);padding:32px">No leads yet for this product. Click <b>Find New Leads →</b> above to search YouTube.</td></tr>`;
  } else {
    $('#dash-table-body').innerHTML = openLeads.slice(0, 12).map((x, idx) => {
      const init = (x.author || 'U').replace(/^@/, '').slice(0, 1).toUpperCase();
      const [intentLbl, intentCls] = inferIntentFromLead(x);
      const thumb = `https://i.ytimg.com/vi/${encodeURIComponent(x.video_id || '')}/mqdefault.jpg`;
      const chanName = x.channel || 'YouTube Channel';
      const chanHref = x.channel_url || (x.channel ? `https://www.youtube.com/results?search_query=${encodeURIComponent(x.channel)}` : x.video_url);
      return `<tr>
        <td style="max-width:270px">
          <div style="display:flex;gap:10px;align-items:flex-start">
            <div class="avatar ${avColors[idx % avColors.length]}" style="width:30px;height:30px;font-size:12px">${esc(init)}</div>
            <div>
              <div style="font-weight:600;color:var(--ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${esc(x.text)}</div>
              <div style="font-size:11.5px;color:var(--mute);margin-top:2px">${esc(x.author)}${x.analysis_stale ? ' · Score outdated' : ''}</div>
            </div>
          </div>
        </td>
        <td style="max-width:230px">
          <div class="tbl-video-cell">
            <img class="tbl-thumb" src="${thumb}" alt="">
            <div style="min-width:0">
              <a href="${esc(x.video_url)}" target="_blank" rel="noopener" style="font-weight:700;color:var(--ink);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(x.video_title || 'YouTube Video')}</a>
              <a href="${esc(chanHref)}" target="_blank" rel="noopener" style="font-size:12px;color:var(--brown);font-weight:600;text-decoration:underline">${esc(chanName)} ↗</a>
            </div>
          </div>
        </td>
        <td><span class="intent-pill ${intentCls}">${esc(intentLbl)}</span></td>
        <td style="max-width:220px;color:var(--mute);font-size:13px">
          <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(x.reply)}</div>
        </td>
        <td><b style="color:var(--brown)">${x.score}/100</b></td>
        <td>
          <div style="display:flex;gap:6px;align-items:center">
            <button class="btn-copy" onclick="copyText(this, ${JSON.stringify(x.reply || '').replace(/"/g, '&quot;')}, '📋 Copy')">📋 Copy</button>
            <a class="btn-outline" style="padding:5px 9px;font-size:12px" href="${esc(x.link)}" target="_blank" rel="noopener" title="Open highlighted comment on YouTube">Open ↗</a>
          </div>
        </td>
      </tr>`;
    }).join('');
  }

  // Render Lead Finder Full Cards (Screen 6)
  $('#lead-count').textContent = `${openLeads.length} lead${openLeads.length === 1 ? '' : 's'}${lockedLeads.length ? ` (${lockedLeads.length} locked on Free plan)` : ''}`;
  $('#leads').innerHTML = l.map((x, idx) => {
    if (x.locked) {
      return `<div class="unlock-callout" style="margin:10px 0">
        <div>
          <span class="intent-pill i-alt">🔒 Match Score · ${x.score}/100</span>
          <div style="font-weight:700;margin-top:4px">Locked buyer lead on Free Plan</div>
          <div style="font-size:13px;color:var(--mute)">Upgrade to Starter or Boost for a larger match allowance and direct source links.</div>
        </div>
        <button class="btn-brown" onclick="showScreen('pricing')">Upgrade Plan →</button>
      </div>`;
    }
    const init = (x.author || 'U').replace(/^@/, '').slice(0, 1).toUpperCase();
    const [intentLbl, intentCls] = inferIntentFromLead(x);
    const chanName = x.channel || 'YouTube Channel';
    const chanHref = x.channel_url || (x.channel ? `https://www.youtube.com/results?search_query=${encodeURIComponent(x.channel)}` : x.video_url);
    const good = x.feedback === 'good', bad = x.feedback === 'bad';
    return `<div class="lead-split-card" style="${bad ? 'opacity:0.55' : ''}">
      <div>
        <div style="display:flex;gap:12px;align-items:flex-start">
          <div class="avatar ${avColors[idx % avColors.length]}">${esc(init)}</div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <b style="font-size:14.5px">${esc(x.author)}</b>
              <span class="intent-pill ${intentCls}">${esc(intentLbl)} · ${x.score}/100</span>
            </div>
            <p style="margin:8px 0;font-size:14.5px;color:var(--ink)">${esc(x.text)}</p>
            <div style="font-size:12.5px;color:var(--mute);margin-bottom:6px"><b>Why this matched:</b> ${esc(x.reason)}</div>
            <div style="font-size:12px;color:var(--mute);margin:6px 0">Posted: ${esc(sourceDate(x.published_at))} · ${esc(x.buyer_type || 'unknown')} classification</div>
            ${x.analysis_stale ? '<div class="status-box run">Previous score is outdated. Reassess saved comments using your current product profile.</div>' : ''}
            <div style="font-size:13px;margin:8px 0"><b>Customer need:</b> ${esc((x.evidence || {}).need || 'Not extracted in this analysis')}<br>
              <b>Matching feature:</b> ${esc((x.evidence || {}).feature || 'Not extracted in this analysis')}<br>
              <b>Supporting words:</b> “${esc((x.evidence || {}).quote || x.text)}”<br>
              <b>Still unknown:</b> ${esc(((x.evidence || {}).unknowns || ['Location, budget and willingness to buy are unverified']).join('; ') || 'No additional unknowns recorded; buyer details remain unverified')}</div>
            <div class="yt-source-links">
              <a href="${esc(chanHref)}" target="_blank" rel="noopener">📺 Channel: ${esc(chanName)} ↗</a>
              <a href="${esc(x.video_url)}" target="_blank" rel="noopener">🎬 Video: ${esc((x.video_title || '').slice(0, 50))} ↗</a>
              <a href="${esc(x.link)}" target="_blank" rel="noopener">💬 Highlighted Comment Link ↗</a>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">

              <button class="btn-copy" style="${good ? 'background:var(--green-bg);border-color:var(--green)' : ''}" onclick="setFeedback(${x.id},'${good ? '' : 'good'}')">👍 Real lead</button>
              <button class="btn-copy" style="${bad ? 'background:var(--rose-bg);border-color:var(--rose)' : ''}" onclick="setFeedback(${x.id},'${bad ? '' : 'bad'}')">${bad ? '↩ Undo' : '🚫 Not real'}</button>
            </div>
          </div>
        </div>
      </div>
      <div class="reply-pane">
        <div>
          <div class="reply-pane-head">
            <span>Suggested reply (editable)</span>
            <div style="display:flex;gap:6px">
              <button class="btn-copy" onclick="copyText(this, $('#r${x.id}').value, '📋 Copy')">📋 Copy</button>
              <a class="btn-brown" style="padding:5px 11px;font-size:12px" href="${esc(x.link)}" target="_blank" rel="noopener">Open & Reply ↗</a>
            </div>
          </div>
          ${outcomeFields(x)}
          <textarea id="r${x.id}" class="field-input" rows="3" style="background:#fff;font-size:13.5px">${esc(x.reply)}</textarea>
        </div>
        <div style="font-size:11.5px;color:var(--mute);margin-top:6px">
          Direct URL: <a href="${esc(x.link)}" target="_blank" rel="noopener" style="text-decoration:underline">${esc(x.link)}</a>
        </div>
      </div>
    </div>`;
  }).join('') || `<div class="finder-card" style="text-align:center;color:var(--mute);padding:32px">No leads in this filter. Click <b>Search</b> above or switch <b>Show matches</b> to 40%+.</div>`;
}

function sourceDate(value) {
  if (!value || Number.isNaN(Date.parse(value))) return 'Date unavailable';
  return new Date(value).toLocaleString();
}
function outcomeFields(x) {
  const stages = ['new','contacted','responded','qualified','purchased','irrelevant'];
  const currencies = ['INR','USD','EUR','GBP','AUD','CAD','SGD','AED'];
  return `<details style="margin:12px 0"><summary style="cursor:pointer;font-weight:700">Outcome: ${esc(x.outcome || 'new')}</summary>
    <label class="field-label" for="outcome-${x.id}">Customer progress</label>
    <select class="field-input" id="outcome-${x.id}">${stages.map(stage=>`<option value="${stage}" ${(x.outcome || 'new') === stage ? 'selected' : ''}>${stage}</option>`).join('')}</select>
    <label class="field-label" for="revenue-${x.id}">Purchase revenue (only when purchased)</label>
    <input class="field-input" id="revenue-${x.id}" type="number" min="0" step="0.01" value="${(x.revenue_minor || 0)/100}">
    <select class="field-input" id="currency-${x.id}" aria-label="Revenue currency">${currencies.map(c=>`<option value="${c}" ${(x.currency || 'INR') === c ? 'selected' : ''}>${c}</option>`).join('')}</select>
    <label class="field-label" for="rejection-${x.id}">Why irrelevant? Required for irrelevant leads</label>
    <textarea class="field-input" id="rejection-${x.id}" maxlength="1000" placeholder="Wrong location, no buying need, unsupported feature…">${esc(x.rejection_reason || '')}</textarea>
    <button class="btn-outline" onclick="saveOutcome(${x.id},this)">Save outcome</button>
    <span id="outcome-message-${x.id}" role="status"></span></details>`;
}
async function saveOutcome(id, button) {
  button.disabled = true;
  try {
    await api(`leads/${id}/outcome`, {stage:$('#outcome-'+id).value, revenue:$('#revenue-'+id).value || '0', currency:$('#currency-'+id).value, rejection_reason:$('#rejection-'+id).value});
    await loadLeads();
  } catch (e) { $('#outcome-message-'+id).textContent=e.message; button.disabled=false; }
}
async function loadWorkspaceMetrics() {
  const element = $('#pilot-metrics');
  try {
    const metrics = await api(`workspaces/${$('#ws').value}/metrics`);
    const funnel = metrics.funnel;
    const revenue = Object.entries(metrics.revenue_minor_by_currency).map(([currency,minor])=>`${currency} ${(minor/100).toFixed(2)}`).join(' · ') || 'No purchases recorded';
    const feedback = metrics.pilot_feedback || {};
    element.hidden=false;
    element.innerHTML=`<b>Customer conversations</b><p>${['contacted','responded','qualified','purchased','irrelevant'].map(stage=>`${stage}: ${funnel[stage] || 0}`).join(' · ')}</p>
      <p>${esc(revenue)} · Manually confirmed useful leads: ${metrics.reviewed_useful}</p>
      <p>Estimated API cost per useful lead: ${metrics.api_cost_per_useful_lead_usd == null ? 'Unavailable — review leads and configure model pricing' : '$'+metrics.api_cost_per_useful_lead_usd.toFixed(4)} (excludes hosting and outreach)</p>
      ${metrics.analysis_stale ? `<p>${metrics.analysis_stale} saved analyses are outdated or unfinished. <button class="btn-outline" onclick="reassessSaved(this)">Reassess saved comments</button></p>` : ''}
      <details><summary style="cursor:pointer">Pilot feedback</summary><label class="field-label" for="pilot-pay">After using these results, would you pay to use this again?</label>
      <select class="field-input" id="pilot-pay">${['undecided','yes','no'].map(value=>`<option value="${value}" ${(feedback.would_pay || 'undecided') === value ? 'selected' : ''}>${value}</option>`).join('')}</select>
      <label class="field-label" for="pilot-notes">What worked, what failed, and what would make this worth paying for?</label>
      <textarea class="field-input" id="pilot-notes" maxlength="2000">${esc(feedback.notes || '')}</textarea>
      <button class="btn-outline" onclick="savePilotFeedback(this)">Save feedback</button><span id="pilot-message" role="status"></span></details>`;
  } catch(e) { element.hidden=false; element.textContent='Could not load outcome metrics: '+e.message; }
}
async function savePilotFeedback(button) {
  button.disabled=true;
  try { await api(`workspaces/${$('#ws').value}/pilot-feedback`,{would_pay:$('#pilot-pay').value,notes:$('#pilot-notes').value}); $('#pilot-message').textContent='Saved'; }
  catch(e) { $('#pilot-message').textContent=e.message; }
  finally { button.disabled=false; }
}
async function reassessSaved(button) {
  button.disabled=true;
  try { const result=await api(`workspaces/${$('#ws').value}/reassess`,{}); startPolling(result.job_id); }
  catch(e) { box('bad',esc(e.message)); button.disabled=false; }
}

async function loadPlan() {
  try { planInfo = await api('plan'); } catch (e) { return; }
  const p = planInfo;
  $('#kpi-searches').textContent = p.searches_used || 0;
  $('#kpi-searches-sub').textContent = p.searches_limit != null ? `Searches used of ${p.searches_limit} (${p.label} Plan)` : `Searches used (${p.label} Plan)`;
  let h = '';
  if (p.searches_limit != null && (p.locked_total > 0 || !p.can_search)) {
    h = `🔒 <b>${p.locked_total} more matches locked</b> · ${esc(p.label)} · ${p.analysis_remaining.toLocaleString()} comments left to analyse. <a href="#" onclick="showScreen('pricing');return false" style="text-decoration:underline;font-weight:800">View plans →</a>`;
  }
  $('#planbar').innerHTML = h;
  $('#planbar').hidden = !h;
  $('#findbtn').disabled = searching || !p.can_search;
}

async function wantUpgrade(planKey) {
  try {
    await api('upgrade-interest', {plan: planKey || 'paid'});
    interestSent = true;
    alert('Thank you! Your upgrade request for the ' + (planKey || 'Pro').toUpperCase() + ' plan has been recorded.');
    openAppDashboard();
  } catch (e) { alert(e.message); }
}

function copyText(btn, t, label) {
  navigator.clipboard.writeText(t).then(() => {
    btn.textContent = '✓ Copied';
    setTimeout(() => btn.textContent = label, 1500);
  });
}
async function setFeedback(id, fb) { await api(`leads/${id}/feedback`, {feedback: fb}); loadLeads(); }
async function mark(id, s) { await api(`leads/${id}/status`, {status: s}); loadLeads(); }
async function exportCsv() {
  if (!$('#ws').value) return;
  const url = apiUrl(`leads/export?workspace_id=${$('#ws').value}&min_score=${$('#level').value}&status=${$('#status-filter').value}`);
  try {
    const r = await fetch(url, { headers: authHeaders(), credentials:'include' });
    if (!r.ok) throw new Error('Could not export CSV');
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `leads_workspace_${$('#ws').value}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    window.location.href = url;
  }
}
async function saveBlocklist() {
  if (!$('#ws').value) return;
  $('#bl-msg').textContent = 'Saving…';
  try {
    await api(`workspaces/${$('#ws').value}/blocklist`, {blocklist: $('#bl').value});
    $('#bl-msg').textContent = '✓ Saved';
    const c = curWs(); if (c) c.blocklist = $('#bl').value;
    setTimeout(() => $('#bl-msg').textContent = '', 2500);
    loadLeads();
  } catch (e) { $('#bl-msg').textContent = e.message; }
}

async function loadAutomationStatus() {}
// ---------- Creator Report ----------
async function report() {
  $('#rs').textContent = '⏳ Analysing channel comments… (1–2 min)';
  try {
    const d = await api('report', {channel_url: $('#ch').value});
    $('#rs').textContent = `✓ Analysed ${d.comments_analysed} comments.`;
    $('#rep').innerHTML = `
      <h3 class="serif">What the audience is asking for</h3>
      ${(d.topics || []).map(t => `<div class="finder-card"><b>${esc(t.title)}</b> <span style="color:var(--mute);font-size:12.5px">~${t.approx_comments} comments</span><p style="color:var(--mute);margin:6px 0 0">“${esc(t.example)}”</p></div>`).join('')}
      <h3 class="serif" style="margin-top:22px">Product ideas and suggested prices to validate</h3>
      ${(d.product_ideas || []).map(p => `<div class="finder-card"><b>${esc(p.name)}</b> · <span class="intent-pill i-alt">${esc(p.format)}</span> · <b>Suggested ₹${p.price_inr}</b><p style="color:var(--mute);margin:6px 0 0">${esc(p.why)}</p></div>`).join('')}
      <h3 class="serif" style="margin-top:22px">Possible customer needs (purchase intent unverified)</h3>
      ${(d.buyer_comments || []).map(b => `<div class="finder-card"><b>${esc(b.author)}</b><p style="margin:6px 0">${esc(b.text)}</p><div style="font-size:12.5px;color:var(--mute)">${esc(b.why)}</div><a href="${esc(b.link)}" target="_blank" rel="noopener">View source comment ↗</a></div>`).join('')}
      <h3 class="serif" style="margin-top:22px">Cold DM to send the creator</h3>
      <div class="finder-card"><pre style="margin:0;white-space:pre-wrap;font-family:inherit">${esc(d.cold_dm)}</pre></div>
    `;
  } catch (e) { $('#rs').textContent = e.message; }
}

// ---------- Keyboard Shortcut (Ctrl+K) & Startup ----------
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    const gs = $('#global-search');
    if (gs && !$('#screen-app').hidden) { e.preventDefault(); gs.focus(); }
  }
});

// Supabase restores the session before private data is requested.
showScreen('landing');
initSupabaseClient().catch(error => { $('#auth-err').textContent=error.message; });
