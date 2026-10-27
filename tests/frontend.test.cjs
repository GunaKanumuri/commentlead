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
