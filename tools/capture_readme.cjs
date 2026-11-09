// Capture only the application page, using an isolated snapshot and actual saved answers.
const {spawn}=require('node:child_process');
const {mkdtemp,readFile,writeFile,mkdir,rm}=require('node:fs/promises');
const {tmpdir}=require('node:os');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,label){const end=Date.now()+25000;while(Date.now()<end){const r=await fn();if(r)return r;await pause(100);}throw Error(label);}
async function connect(url){const ws=new WebSocket(url);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let seq=0;const pending=new Map();ws.addEventListener('message',({data})=>{const m=JSON.parse(data);const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}});const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});return {send,close:()=>ws.close(),evaluate:async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;}};}
async function main(){
 const profile=await mkdtemp(path.join(tmpdir(),'studyread-capture-'));
 const backend=spawn(path.join(root,'.venv/Scripts/python.exe'),['-u','-X','utf8','tools/snapshot_server.py'],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
 let text='';backend.stdout.on('data',d=>text+=d);backend.stderr.on('data',d=>process.stderr.write(d));
 const info=await until(()=>{try{return JSON.parse(text.trim().split('\n')[0]);}catch{return null;}},'snapshot server');
 const chrome=spawn(process.env.CHROME_PATH||path.resolve(root,'../chrome-win64/chrome.exe'),['--headless=new','--no-first-run','--disable-gpu','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
 let page;
 try{
  const port=await until(async()=>{try{return(await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];}catch{return null;}},'Chrome');
  const targets=await fetch(`http://127.0.0.1:${port}/json/list`).then(r=>r.json());page=await connect(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await page.send('Emulation.setDeviceMetricsOverride',{width:1440,height:940,deviceScaleFactor:1,mobile:false});
  await page.send('Page.navigate',{url:info.url});
  await until(()=>page.evaluate("window.studyread?.state.books.length>0&&document.querySelectorAll('.book-card img').length>0"),'library');
  const dest=path.join(root,'docs/screenshots');await mkdir(dest,{recursive:true});
  async function capture(name){await pause(600);const r=await page.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(path.join(dest,name),Buffer.from(r.data,'base64'));}
  await capture('studyread-library.png');
  await page.evaluate('window.studyread.openBook(window.studyread.state.books[0].id)');
  await until(()=>page.evaluate("!!document.querySelector('.page canvas')&&window.studyread.state.messageRows.length===4"),'reader and actual chat');
  // Start of the actual first explanation includes its title, equations and source page.
  await page.evaluate("document.getElementById('messages').scrollTop=0");
  await capture('studyread-reader.png');
  await page.evaluate("document.getElementById('messages').scrollTop=500");
  await capture('studyread-math.png');
  console.log('Captured actual Morin textbook and saved real-model explanations.');
 }finally{page?.close();chrome.kill();backend.kill();await pause(700);await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});await rm(info.data,{recursive:true,force:true,maxRetries:10,retryDelay:100});}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
