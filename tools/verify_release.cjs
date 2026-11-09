// Verify the packaged executable's actual WebView2, not the development browser.
const {spawn}=require('node:child_process');
const {mkdtemp,rm,writeFile,mkdir}=require('node:fs/promises');
const {tmpdir}=require('node:os');
const path=require('node:path');
const http=require('node:http');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,label,seconds=30){const end=Date.now()+seconds*1000;while(Date.now()<end){const r=await fn();if(r)return r;await pause(150);}throw new Error('Timeout: '+label);}
async function connect(url){
 const ws=new WebSocket(url);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
 let seq=0;const wait=new Map();const errors=[];
 ws.addEventListener('message',({data})=>{const m=JSON.parse(data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);const p=wait.get(m.id);if(p){wait.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}});
 const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>reject(Error('CDP timeout: '+method)),30000);wait.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
 return {errors,send,close:()=>ws.close(),evaluate:async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;}};
}
async function main(){
 const dir=await mkdtemp(path.join(tmpdir(),'studyread-packaged-'));
 const temporary=http.createServer();await new Promise(r=>temporary.listen(0,'127.0.0.1',r));const port=temporary.address().port;await new Promise(r=>temporary.close(r));
 const sample=process.env.STUDYREAD_SAMPLE_PDF;
 assert.ok(sample,'Set STUDYREAD_SAMPLE_PDF to a real PDF for release verification');
 const exe=path.join(root,'dist/v0.1.0/StudyRead/StudyRead.exe');
 const child=spawn(exe,[sample],{cwd:path.dirname(exe),windowsHide:true,stdio:'ignore',env:{...process.env,STUDYREAD_DATA_DIR:dir,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:'--remote-debugging-port='+port}});
 let page;
 try{
  const target=await until(async()=>{try{const targets=await fetch(`http://127.0.0.1:${port}/json/list`).then(r=>r.json());return targets.find(t=>t.type==='page'&&t.url.includes('127.0.0.1:'));}catch{return null;}},'packaged WebView2');
  page=await connect(target.webSocketDebuggerUrl);await page.send('Runtime.enable');
  await until(()=>page.evaluate("!!window.studyread&&document.querySelectorAll('.book-card').length===1"),'packaged library');
  assert.equal(await page.evaluate('window.studyread.state.books[0].pages'),739);
  assert.equal(await page.evaluate('typeof pywebview.api.choose_files'),'function');
  await page.evaluate('window.studyread.openBook(window.studyread.state.books[0].id)');
  await page.evaluate("document.getElementById('page-number').value=24;document.getElementById('page-number').dispatchEvent(new Event('change'))");
  await until(()=>page.evaluate("!!document.querySelector('.page[data-page-number=\"24\"] canvas')&&document.querySelector('.page[data-page-number=\"24\"] .textLayer')?.textContent.length>50"),'packaged original PDF page');
  assert.equal(await page.evaluate("window.studyread.mathMarkdown('$$F=ma$$').querySelectorAll('.katex').length"),1);
  await until(()=>page.evaluate("(()=>{const v=window.studyread.viewer,p=v.getPageView(23),w=document.getElementById('pdf-container').clientWidth;return v.currentPageNumber===24&&p.div.offsetWidth<=w&&p.div.offsetWidth>w-65})()"),'mixed-size PDF fit width');
  assert.deepEqual(page.errors,[]);
  await mkdir(path.join(root,'_test_artifacts'),{recursive:true});
  const shot=await page.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  await writeFile(path.join(root,'_test_artifacts/packaged-reader.png'),Buffer.from(shot.data,'base64'));
  console.log('PACKAGED PASS: real WebView2, 739-page book, chapter navigation, PDF canvas, selectable text, math and native bridge');
 } finally{
  page?.close();child.kill();await pause(1000);
  await rm(dir,{recursive:true,force:true,maxRetries:20,retryDelay:250});
 }
}
main().catch(e=>{console.error(e);process.exitCode=1;});
