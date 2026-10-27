const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const nodes=new Map();const node=s=>{if(!nodes.has(s))nodes.set(s,{value:'',checked:false,hidden:false,textContent:'',innerHTML:'',addEventListener(){},focus(){},reset(){},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(s);};
 const scope=vm.createContext({window:{APP_CONFIG:{apiBaseUrl:'https://api.example.test'},location:{search:'?utm_source=reddit'}},URL,URLSearchParams,console,document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){},body:{classList:{add(){},remove(){}}}},fetch:async()=>({ok:true,json:async()=>({ok:true})})});
 for(const file of ['api.js','app.js'])vm.runInContext(fs.readFileSync('frontend/assets/'+file,'utf8'),scope);
 return {scope,node};
}
test('public requests use API without authentication',async()=>{
 const {scope}=setup();let request;scope.fetch=async(url,options)=>{request={url,options};return {ok:true,json:async()=>({ok:true})};};
 await vm.runInContext("api('pricing')",scope);assert.equal(request.url,'https://api.example.test/api/pricing');assert.equal(request.options.headers.Authorization,undefined);
});
test('waitlist requires consent then saves launch details',async()=>{
 const {scope,node}=setup();let body,calls=0;scope.fetch=async(url,options)=>{calls++;body=JSON.parse(options.body);return {ok:true,json:async()=>({ok:true})};};
 vm.runInContext("openWaitlist('matched-leads')",scope);node('#waitlist-email').value='founder@example.test';
 await vm.runInContext('submitWaitlist()',scope);assert.equal(calls,0);
 node('#waitlist-consent').checked=true;await vm.runInContext('submitWaitlist()',scope);
 assert.equal(body.source,'reddit');assert.equal(body.interest,'matched-leads');assert.equal(body.consent,true);assert.equal(node('#waitlist-success').hidden,false);
});
test('storage failure never claims success',async()=>{
 const {scope,node}=setup();vm.runInContext('openWaitlist()',scope);node('#waitlist-email').value='founder@example.test';node('#waitlist-consent').checked=true;
 scope.fetch=async()=>({ok:false,status:503,json:async()=>({detail:'private database error'})});await vm.runInContext('submitWaitlist()',scope);
 assert.equal(node('#waitlist-success').hidden,true);assert.match(node('#waitlist-error').textContent,/temporarily unavailable/);assert.equal(node('#waitlist-submit').disabled,false);
});
test('comments escaped and links restricted',()=>{
 const {scope,node}=setup();vm.runInContext(`renderPreview({leads:[{text:'<script>bad</script>',link:'javascript:alert(1)'}]})`,scope);
 assert.match(node('#preview-leads-list').innerHTML,/&lt;script&gt;/);assert.doesNotMatch(node('#preview-leads-list').innerHTML,/javascript:/);
});

test('switching search modes explains each input and preserves the typed topic',()=>{
 const {scope,node}=setup();node('#landing-query').value='invoicing for freelancers';
 vm.runInContext("setPreviewMode('video')",scope);
 assert.equal(node('#landing-query').type,'url');assert.match(node('#query-label').textContent,/YouTube video/);
 node('#landing-query').value='https://youtu.be/abcdefghijk';
 vm.runInContext("setPreviewMode('topic')",scope);
 assert.equal(node('#landing-query').value,'invoicing for freelancers');assert.match(node('#query-help').textContent,/not your product website/);
});
test('invalid video links and URLs in topic mode never consume a preview',async()=>{
 const {scope,node}=setup();let calls=0;scope.fetch=async()=>{calls++;throw Error('Unexpected request');};
 vm.runInContext("setPreviewMode('video')",scope);node('#landing-query').value='https://example.com/product';
 await vm.runInContext('runFreePreview()',scope);assert.equal(calls,0);assert.match(node('#preview-error').textContent,/YouTube video link/);
 vm.runInContext("setPreviewMode('topic')",scope);node('#landing-query').value='https://youtu.be/abcdefghijk';
 await vm.runInContext('runFreePreview()',scope);assert.equal(calls,0);assert.match(node('#preview-error').textContent,/choose/);
 assert.equal(vm.runInContext("isYouTubeVideoLink('https://youtu.be/abcdefghijk')",scope),true);
 assert.equal(vm.runInContext("isYouTubeVideoLink('https://youtube.com/@founder')",scope),false);
});

test('topic suggestions switch out of video mode without starting a search',()=>{
 const {scope,node}=setup();vm.runInContext("setPreviewMode('video');chooseTopic('AI text to video tools')",scope);
 assert.equal(node('#search-topic').checked,true);assert.equal(node('#search-video').checked,false);
 assert.equal(node('#landing-query').type,'text');assert.equal(node('#landing-query').value,'AI text to video tools');
 assert.equal(node('#topic-suggestions').hidden,false);
});

test('BharatChitra example separates demonstrated capabilities from planned features',()=>{
 const {scope,node}=setup();vm.runInContext('useBharatChitraExample()',scope);
 assert.equal(node('#product-readiness').value,'prototype');
 assert.match(node('#product-description').value,/demonstrated in development/);
 assert.doesNotMatch(node('#product-description').value,/YouTube scheduling/);
 assert.match(node('#product-constraints').value,/English remain unverified/);
 assert.match(node('#product-constraints').value,/do not claim free or unlimited/);
});
test('missing product profile blocks provider requests and empty results never fill with comments',async()=>{
 const {scope,node}=setup();let calls=0;scope.fetch=async()=>{calls++;throw Error('Unexpected');};
 node('#landing-query').value='AI video tools';await vm.runInContext('runFreePreview()',scope);
 assert.equal(calls,0);assert.match(node('#preview-error').textContent,/features that work today/);
 vm.runInContext('renderPreview({leads:[],stats:{videos_checked:3,comments_read:105,comments_assessed:60},message:"No relevant opportunities found"})',scope);
 assert.equal(node('#preview-heading').textContent,'No relevant opportunities found');
 assert.equal(node('#preview-leads-list').innerHTML,'');assert.match(node('#preview-summary').textContent,/105 comments read/);
});
test('matching evidence is escaped and includes unknowns',()=>{
 const {scope,node}=setup();vm.runInContext(`renderPreview({leads:[{text:'Need Telugu narration',evidence:{need:'<script>bad</script>',quote:'Telugu narration',feature:'Telugu voice narration',reason:'Requested language',unknowns:['Budget unverified']}}]})`,scope);
 assert.match(node('#preview-leads-list').innerHTML,/&lt;script&gt;/);assert.match(node('#preview-leads-list').innerHTML,/Budget unverified/);
 assert.match(node('#preview-leads-list').innerHTML,/Your matching feature/);
});
