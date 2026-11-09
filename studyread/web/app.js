import * as pdfjs from './vendor/pdfjs/build/pdf.mjs';
const { EventBus, PDFViewer, PDFLinkService, PDFFindController } = await import('./vendor/pdfjs/web/pdf_viewer.mjs');
pdfjs.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdfjs/build/pdf.worker.mjs', import.meta.url).href;
const $ = id => document.getElementById(id);
const token = location.pathname.split('/')[1];
const state = { books: [], settings: {}, category: 'all', recentMore: false, book: null, session: null,
  doc: null, task: null, selected: null, pendingSelection: null, crop: false, job: null, progressTimer: null,
  restoring: false, opening: 0, messageRows: [], polling: 0 };
const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const categoryNames = {all:'全部书籍', math:'数学', physics:'物理', other:'其他'};
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500); }
async function api(path, data, options={}) {
  const response = await fetch('api/'+path, { method:data === undefined?'GET':'POST',
    headers: data === undefined?{}:{'Content-Type':'application/json','X-StudyRead':token},
    body:data === undefined?undefined:JSON.stringify(data), ...options });
  const result = await response.json();
  if(!response.ok) throw new Error(result.error || '操作失败');
  return result;
}
function action(fn) { return async event => { try { await fn(event); } catch(error) { toast(error.message); } }; }
function bind(id, event, fn) { $(id).addEventListener(event, action(fn)); }
function activeProfile() { return state.settings.profiles?.find(p => p.id === state.settings.activeProfile); }
function updateModel() { const p=activeProfile(); $('model-indicator').textContent=p?`${p.model}${p.vision?' · 可识图':''}`:'配置模型'; }
function relativeTime(value) { if(!value)return '尚未开始'; const diff=Date.now()-value; if(diff<60000)return '刚刚'; if(diff<3600000)return `${Math.floor(diff/60000)} 分钟前`; if(diff<86400000)return `${Math.floor(diff/3600000)} 小时前`; return new Date(value).toLocaleDateString('zh-CN'); }

async function refreshLibrary() {
  const data = await api('bootstrap');
  state.books=data.books; state.settings=data.settings;
  $('version').textContent='StudyRead v'+data.version;
  updateModel(); renderLibrary();
}
function renderLibrary() {
  for(const key of Object.keys(categoryNames)) $(key+'-count').textContent=state.books.filter(b => key==='all'||b.category===key).length;
  $('shelf-title').textContent=categoryNames[state.category];
  const query=$('book-search').value.toLocaleLowerCase();
  const books=state.books.filter(b => (state.category==='all'||b.category===state.category)&&`${b.title} ${b.author} ${b.filename}`.toLocaleLowerCase().includes(query));
  const sort=$('book-sort').value;
  books.sort((a,b)=>sort==='title'?a.title.localeCompare(b.title):sort==='added'?b.added_at-a.added_at:b.last_read_at-a.last_read_at||b.added_at-a.added_at);
  $('book-grid').replaceChildren();
  for(const b of books) {
    const card=document.createElement('article'); card.className='book-card';card.dataset.book=b.id;
    card.innerHTML=`<div class="book-cover"><img loading="lazy" src="covers/${b.id}.png" alt="${esc(b.title)}封面"></div><button class="book-title">${esc(b.title)}</button><button class="book-menu icon-button" title="书籍信息">⋯</button><div class="book-info">${esc(categoryNames[b.category])} · ${b.pages} 页${b.last_read_at?` · 读到 ${b.page} 页`:''}</div><div class="book-progress"><i style="width:${b.last_read_at?b.page/b.pages*100:0}%"></i></div>`;
    card.querySelector('.book-cover').onclick=action(()=>openBook(b.id)); card.querySelector('.book-title').onclick=action(()=>openBook(b.id));
    card.querySelector('.book-menu').onclick=()=>editBook(b); $('book-grid').append(card);
  }
  $('empty-library').hidden=state.books.length!==0;
  if(state.books.length&&!books.length) $('book-grid').textContent='没有找到匹配的书籍。';
  const recent=state.books.filter(b=>b.last_read_at).sort((a,b)=>b.last_read_at-a.last_read_at);
  $('recent-section').hidden=!recent.length;
  $('recent-more').textContent=state.recentMore?'收起 ↑':'更多 →';
  $('recent-books').replaceChildren();
  for(const b of recent.slice(0,state.recentMore?100:3)) {
    const item=document.createElement('div');item.className='recent-card';
    item.innerHTML=`<img src="covers/${b.id}.png" alt=""><div><strong>${esc(b.title)}</strong><small>PDF 第 ${b.page} / ${b.pages} 页 · ${relativeTime(b.last_read_at)}</small></div>`;
    item.onclick=action(()=>openBook(b.id));$('recent-books').append(item);
  }
}
document.querySelectorAll('[data-category]').forEach(btn=>btn.onclick=()=>{
  state.category=btn.dataset.category;document.querySelectorAll('[data-category]').forEach(b=>b.classList.toggle('active',b===btn));renderLibrary();
});
bind('book-search','input',renderLibrary);bind('book-sort','change',renderLibrary);
bind('recent-more','click',()=>{state.recentMore=!state.recentMore;renderLibrary();});

async function importBooks() {
  if(window.pywebview?.api) {
    const paths=await window.pywebview.api.choose_files(); if(!paths?.length)return;
    $('import-books').disabled=true; $('import-books').textContent='正在导入…';
    try {
      const results=await api('import',{paths,category:state.category==='all'?'physics':state.category});
      const errors=results.filter(r=>r.error);toast(errors.length?errors.map(r=>r.filename+'：'+r.error).join('；'):`已导入 ${results.length} 本书籍`);
      await refreshLibrary();
    } finally { $('import-books').disabled=false;$('import-books').textContent='＋ 添加 PDF 书籍'; }
  } else $('file-upload').click();
}
bind('import-books','click',importBooks);bind('empty-import','click',importBooks);
bind('file-upload','change',async()=>{
  $('import-books').disabled=true;$('import-books').textContent='正在导入…';
  try {
    for(const file of $('file-upload').files) {
      const response=await fetch(`api/upload?category=${state.category==='all'?'physics':state.category}`,{method:'POST',headers:{'X-StudyRead':token,'X-Filename':encodeURIComponent(file.name)},body:file});
      const result=await response.json();if(!response.ok)throw new Error(result.error);
    }
    await refreshLibrary();toast('PDF 已加入书架');
  } finally { $('file-upload').value='';$('import-books').disabled=false;$('import-books').textContent='＋ 添加 PDF 书籍'; }
});
let editedBook=null;
function editBook(b){editedBook=b;$('edit-title').value=b.title;$('edit-category').value=b.category;$('edit-book-dialog').showModal();}
bind('edit-close','click',()=>$('edit-book-dialog').close());
bind('save-book','click',async()=>{await api('book/update',{id:editedBook.id,title:$('edit-title').value,category:$('edit-category').value});$('edit-book-dialog').close();await refreshLibrary();});
bind('remove-book','click',async()=>{if(!confirm(`移出《${editedBook.title}》？\n本工具中的书籍副本及会话将删除。原始 PDF 保留。`))return;await api('book/remove',{id:editedBook.id});$('edit-book-dialog').close();await refreshLibrary();});

const eventBus=new EventBus();
const linkService=new PDFLinkService({eventBus,externalLinkTarget:2});
const findController=new PDFFindController({eventBus,linkService});
const viewer=new PDFViewer({container:$('pdf-container'),viewer:$('pdf-viewer'),eventBus,linkService,findController,
  textLayerMode:1,annotationMode:1,enableAutoLinking:false,enableDetailCanvas:false,maxCanvasPixels:12_000_000,
  imageResourcesPath:new URL('./vendor/pdfjs/web/images/',import.meta.url).href});
linkService.setViewer(viewer);
window.studyread={state,viewer,eventBus,openBook,api}; // 本地调试与集成验证，无密钥数据。
function scaleValue(value){return value==='width'?'page-width':value==='page'?'page-fit':value;}
function currentPage(){return viewer.currentPageNumber||state.book?.page||1;}
let fitFrame=0;
function scheduleFit(){
  cancelAnimationFrame(fitFrame);
  fitFrame=requestAnimationFrame(()=>{
    const mode=$('pdf-zoom').value;
    // Lazy page views initially inherit the cover's dimensions. Fit only once
    // the current page has its own viewport; PDF.js preserves the PDF location.
    if(!state.doc||$('reader').hidden||!['width','page'].includes(mode))return;
    if(viewer.getPageView(currentPage()-1)?.pdfPage)viewer.currentScaleValue=scaleValue(mode);
  });
}
new ResizeObserver(scheduleFit).observe($('pdf-container'));
function updateSource(){const page=state.selected?.page||currentPage();$('source-page').textContent=`引用 PDF 第 ${page} 页`;$('attach-page').disabled=!!state.selected?.rect;if(state.selected?.rect)$('attach-page').checked=false;}
eventBus.on('pagechanging',({pageNumber,pageLabel})=>{
  $('page-number').value=pageNumber;$('pdf-page-label').textContent=pageLabel&&pageLabel!==String(pageNumber)?`PDF 第 ${pageNumber} 页 · 书内页码 ${pageLabel}`:`PDF 第 ${pageNumber} 页`;
  updateSource();updateOutline(pageNumber);scheduleProgress();scheduleFit();
});
eventBus.on('updateviewarea',scheduleProgress);
eventBus.on('updatefindmatchescount',({matchesCount})=>{$('find-count').textContent=matchesCount.total?`${matchesCount.current}/${matchesCount.total}`:'无匹配';});
eventBus.on('pagerendered',({pageNumber,error})=>{if(error)toast('此页渲染失败，可尝试重新打开书籍');if(state.book&&pageNumber===currentPage()){$('pdf-loading').hidden=true;scheduleFit();}});
function renderOutline(){
  const query=$('outline-search').value.toLowerCase();$('outline-list').replaceChildren();
  for(const [level,title,page] of state.book.toc) {
    if(!title.toLowerCase().includes(query)||page<1)continue;
    const btn=document.createElement('button');btn.className='outline-entry'+(level===1?' chapter':'');btn.textContent=title;btn.dataset.page=page;
    btn.style.paddingLeft=(5+Math.min(level-1,4)*12)+'px';btn.title=`PDF 第 ${page} 页`;btn.onclick=()=>jump(page);$('outline-list').append(btn);
  }
  if(!$('outline-list').children.length)$('outline-list').textContent=query?'无匹配章节':'此 PDF 没有内置目录，可用页码跳转或搜索正文。';
  updateOutline(currentPage());
}
function updateOutline(page){
  let last=null;for(const btn of $('outline-list').children){btn.classList.remove('active');if(Number(btn.dataset.page)<=page)last=btn;}
  last?.classList.add('active');
}
function jump(page){if(!state.doc)return;const n=Math.max(1,Math.min(state.book.pages,Number(page)||1));viewer.currentPageNumber=n;viewer.update();}
bind('outline-search','input',renderOutline);
bind('page-number','change',()=>jump($('page-number').value));
bind('prev-page','click',()=>jump(currentPage()-1));bind('next-page','click',()=>jump(currentPage()+1));
bind('pdf-zoom','change',()=>{viewer.currentScaleValue=scaleValue($('pdf-zoom').value);scheduleProgress();});
function toggleOutline(show){$('outline-pane').style.display=show?'flex':'none';$('show-outline').hidden=show;requestAnimationFrame(()=>{if(state.doc)viewer.currentScaleValue=scaleValue($('pdf-zoom').value);});}
bind('hide-outline','click',()=>toggleOutline(false));bind('show-outline','click',()=>toggleOutline(true));
bind('find-toggle','click',()=>{$('find-bar').hidden=!$('find-bar').hidden;if(!$('find-bar').hidden)$('pdf-find').focus();});
function find(again=false,previous=false){eventBus.dispatch('find',{source:window,type:again?'again':'',query:$('pdf-find').value,phraseSearch:true,caseSensitive:false,entireWord:false,highlightAll:true,findPrevious:previous});}
bind('pdf-find','input',()=>find());bind('find-next','click',()=>find(true));bind('find-prev','click',()=>find(true,true));
bind('pdf-find','keydown',e=>{if(e.key==='Enter'){e.preventDefault();find(true,e.shiftKey);}});
bind('find-close','click',()=>{$('find-bar').hidden=true;eventBus.dispatch('findbarclose',{source:window});});
document.addEventListener('keydown',e=>{if(!state.book)return;if((e.ctrlKey||e.metaKey)&&e.key==='f'&&!$('settings-dialog').open){e.preventDefault();$('find-bar').hidden=false;$('pdf-find').focus();}if(e.key==='Escape'){setCrop(false);$('selection-action').hidden=true;}});

async function openBook(id){
  await saveProgress();
  const openId=++state.opening;++state.polling;state.job=null;
  state.restoring=true;clearTimeout(state.progressTimer);state.selected=null;state.pendingSelection=null;setCrop(false);
  $('context-chip').hidden=true;$('selection-action').hidden=true;$('pdf-loading').hidden=false;$('find-bar').hidden=true;
  $('library').hidden=true;$('reader').hidden=false;
  try {
    if(state.task)await state.task.destroy();
    viewer.setDocument(null);linkService.setDocument(null);state.doc=null;
    const info=await api('book?id='+encodeURIComponent(id));if(openId!==state.opening)return;
    state.book=info;state.session=info.current_session;
    $('reader-title').textContent=info.title;$('reader-subtitle').textContent=`${categoryNames[info.category]} · ${info.pages} 页 · 对话保存在本机`;
    $('page-total').textContent='/ '+info.pages;$('page-number').max=info.pages;$('page-number').value=info.page;
    $('pdf-zoom').value=info.zoom;renderOutline();renderSessions();await loadMessages();
    state.task=pdfjs.getDocument({url:`pdf/${id}.pdf`,cMapUrl:new URL('./vendor/pdfjs/cmaps/',import.meta.url).href,cMapPacked:true,
      standardFontDataUrl:new URL('./vendor/pdfjs/standard_fonts/',import.meta.url).href,wasmUrl:new URL('./vendor/pdfjs/wasm/',import.meta.url).href,
      disableAutoFetch:true,disableStream:true,rangeChunkSize:262144,isEvalSupported:false,enableXfa:false});
    state.doc=await state.task.promise;if(openId!==state.opening)return;
    const initialPage=await state.doc.getPage(info.page);if(openId!==state.opening)return;
    await new Promise(resolve=>{
      const ready=()=>{eventBus.off('pagesinit',ready);const target=viewer.getPageView(info.page-1);if(!target.pdfPage)target.setPdfPage(initialPage);jump(info.page);viewer.currentScaleValue=scaleValue(info.zoom);resolve();};
      eventBus.on('pagesinit',ready);viewer.setDocument(state.doc);linkService.setDocument(state.doc);
    });
    const labels=await state.doc.getPageLabels();if(labels)viewer.setPageLabels(labels);
    // 页面首次渲染后应用页内比例，缩放与窗口大小变化不会使阅读跳到其他页。
    await new Promise(resolve=>{let finished=false;const done=()=>{if(finished)return;finished=true;eventBus.off('pagerendered',rendered);clearTimeout(timer);resolve();};const rendered=({pageNumber})=>{if(pageNumber===info.page)done();};const timer=setTimeout(done,4000);eventBus.on('pagerendered',rendered);});
    if(openId!==state.opening)return;
    const pageView=viewer.getPageView(info.page-1);
    if(pageView){const container=$('pdf-container');container.scrollTop+=pageView.div.getBoundingClientRect().top-container.getBoundingClientRect().top+info.position*pageView.div.offsetHeight;}
    state.restoring=false;$('pdf-loading').hidden=true;updateSource();await saveProgress();
  } catch(error){state.restoring=false;$('pdf-loading').textContent='PDF 打开失败：'+error.message;throw error;}
}
function scheduleProgress(){if(state.restoring||!state.book||!state.doc)return;clearTimeout(state.progressTimer);state.progressTimer=setTimeout(()=>saveProgress().catch(e=>{$('save-state').textContent='保存失败';toast(e.message);}),600);}
async function saveProgress(){
  if(state.restoring||!state.book||!state.doc||$('reader').hidden)return;
  clearTimeout(state.progressTimer);const page=currentPage();const view=viewer.getPageView(page-1);const container=$('pdf-container');
  const position=view?Math.max(0,Math.min(1,(container.getBoundingClientRect().top-view.div.getBoundingClientRect().top)/view.div.offsetHeight)):0;
  const saved=await api('progress',{bookId:state.book.id,page,position,zoom:$('pdf-zoom').value},{keepalive:true});
  Object.assign(state.book,saved);$('save-state').textContent='位置已保存';
}
bind('back-library','click',async()=>{await saveProgress();saveDraft();++state.polling;state.job=null;state.book=null;state.session=null;$('reader').hidden=true;$('library').hidden=false;await refreshLibrary();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){saveDraft();saveProgress().catch(()=>{});}});
window.addEventListener('pagehide',()=>{saveDraft();saveProgress().catch(()=>{});});

function setContext(value){state.selected=value;$('context-chip').hidden=!value;if(value){$('context-label').textContent=`${value.rect?'框选公式 / 图示':'选中原文'} · PDF 第 ${value.page} 页`;$('context-preview').textContent=value.text||'所选区域将以图片发送，请使用支持图片的模型';}$('selection-action').hidden=true;updateSource();$('question').focus();}
bind('clear-context','click',()=>setContext(null));
$('pdf-container').addEventListener('mouseup',e=>{
  if(state.crop)return;
  const selection=window.getSelection();const text=selection?.toString().trim();
  const node=selection?.anchorNode?.parentElement;const start=node?.closest('.page');const end=selection?.focusNode?.parentElement?.closest('.page');
  if(!text||!start||!$('pdf-viewer').contains(start)){ $('selection-action').hidden=true;return; }
  if(start!==end){toast('请在同一页内选中要提问的段落，跨页问题可直接描述页码');return;}
  state.pendingSelection={text:text.slice(0,12000),page:Number(start.dataset.pageNumber)};
  $('selection-action').style.left=Math.min(innerWidth-150,Math.max(5,e.clientX-40))+'px';$('selection-action').style.top=Math.min(innerHeight-45,e.clientY+12)+'px';$('selection-action').hidden=false;
});
$('selection-action').addEventListener('mousedown',e=>e.preventDefault());bind('selection-action','click',()=>setContext(state.pendingSelection));
function setCrop(value){state.crop=value;$('crop-mode').classList.toggle('active',value);$('pdf-container').classList.toggle('cropping',value);$('crop-box').hidden=true;if(value){window.getSelection()?.removeAllRanges();$('selection-action').hidden=true;toast('在一页内拖动框选公式或图示；Esc 取消');}}
bind('crop-mode','click',()=>setCrop(!state.crop));
let cropStart=null;
$('pdf-container').addEventListener('pointerdown',e=>{
  if(!state.crop||e.button!==0)return;const page=e.target.closest('.page');if(!page)return;e.preventDefault();e.stopPropagation();
  const rect=page.getBoundingClientRect();cropStart={x:e.clientX,y:e.clientY,page:Number(page.dataset.pageNumber),bounds:rect};
  $('pdf-container').setPointerCapture(e.pointerId);$('crop-box').hidden=false;drawCrop(e.clientX,e.clientY);
},true);
function drawCrop(x,y){if(!cropStart)return;const b=cropStart.bounds;x=Math.max(b.left,Math.min(b.right,x));y=Math.max(b.top,Math.min(b.bottom,y));const box=$('crop-box');Object.assign(box.style,{left:Math.min(x,cropStart.x)+'px',top:Math.min(y,cropStart.y)+'px',width:Math.abs(x-cropStart.x)+'px',height:Math.abs(y-cropStart.y)+'px'});}
$('pdf-container').addEventListener('pointermove',e=>{if(cropStart)drawCrop(e.clientX,e.clientY);});
$('pdf-container').addEventListener('pointerup',e=>{
  if(!cropStart)return;const s=cropStart;const b=s.bounds;cropStart=null;setCrop(false);
  const x=Math.max(b.left,Math.min(b.right,e.clientX)),y=Math.max(b.top,Math.min(b.bottom,e.clientY));
  if(Math.abs(x-s.x)<6||Math.abs(y-s.y)<6){toast('请框选稍大的区域');return;}
  setContext({page:s.page,text:'',rect:[(Math.min(x,s.x)-b.left)/b.width,(Math.min(y,s.y)-b.top)/b.height,(Math.max(x,s.x)-b.left)/b.width,(Math.max(y,s.y)-b.top)/b.height]});
});

function mathMarkdown(text){
  const maths=[];
  const protectedText=text.replace(/```[\s\S]*?```|`[^`\n]+`|\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([^\n]+?)\\\)|\$([^$\n]+?)\$/g,(all,display,bracket,paren,inline)=>{
    if(all.startsWith('`'))return all;
    const id=maths.length;maths.push({text:display??bracket??paren??inline,display:display!==undefined||bracket!==undefined});
    return `<span data-study-math="${id}"></span>`;
  });
  const html=DOMPurify.sanitize(marked.parse(protectedText,{breaks:false}),{FORBID_TAGS:['img','iframe','style','form','input','button'],FORBID_ATTR:['style']});
  const fragment=document.createElement('div');fragment.innerHTML=html;
  for(const node of fragment.querySelectorAll('[data-study-math]')){const m=maths[Number(node.dataset.studyMath)];if(m)katex.render(m.text,node,{displayMode:m.display,throwOnError:false,trust:false,strict:'ignore'});}
  for(const a of fragment.querySelectorAll('a')){a.target='_blank';a.rel='noopener noreferrer';}
  return fragment;
}
window.studyread.mathMarkdown=mathMarkdown;
function renderMessage(m){
  const el=document.createElement('article');el.className='message '+m.role;el.dataset.message=m.id;
  const head=document.createElement('div');head.className='message-head';head.textContent=m.role==='user'?'你 · 提问':'理读 · 解答';el.append(head);
  const c=m.context||{};
  if(c.page){const source=document.createElement('button');source.className='message-source';source.innerHTML=`PDF 第 ${c.page} 页${c.rect?' · 所选公式 / 图示':''}${c.selection?`<span class="source-quote">${esc(c.selection)}</span>`:''}`;source.onclick=()=>jump(c.page);el.append(source);}
  for(const name of new Set([c.image,...(c.images||[])].filter(Boolean))){const img=document.createElement('img');img.className='context-image';img.src='attachments/'+name;img.alt=name===c.image?'提问时引用的 PDF 图片':'提问时粘贴的图片';el.append(img);}
  const body=document.createElement('div');body.className='message-body';
  if(m.role==='user')body.textContent=m.content;else body.append(mathMarkdown(m.content|| (m.status==='streaming'?'正在思考…':'')));
  el.append(body);
  if(m.status!=='complete'&&m.status!=='streaming'){const foot=document.createElement('div');foot.className='message-footer';foot.textContent=m.error||'回答中断，内容已保存';
    if(m===state.messageRows.at(-1)&&m.role==='assistant'){const btn=document.createElement('button');btn.className='text-button';btn.textContent='重试';btn.onclick=action(async()=>{await api('retry',{sessionId:state.session,messageId:m.id});await loadMessages();});foot.append(btn);}el.append(foot);}
  return el;
}
function renderMessages(){
  const area=$('messages');area.replaceChildren();
  if(!state.messageRows.length){area.innerHTML='<div class="chat-empty"><div class="empty-symbol">why?</div><h3>把疑问留在这一页</h3><p>选中一段原文，或框选一个公式，再开始提问。上下文会跟随每条问题保存。</p><button class="suggestion">这一页主要在讲什么？请解释关键概念。</button><button class="suggestion">这里的公式是怎么推导出来的？</button><button class="suggestion">能给我一个直观的物理图像或简单例子吗？</button></div>';
    area.querySelectorAll('.suggestion').forEach(btn=>btn.onclick=()=>{$('question').value=btn.textContent;$('question').focus();});
  }else for(const m of state.messageRows)area.append(renderMessage(m));
  area.scrollTop=area.scrollHeight;
}
function renderSessions(){
  $('session-select').replaceChildren();for(const s of state.book.sessions){const option=new Option(s.title,s.id);$('session-select').add(option);}$('session-select').value=state.session;
}
function saveDraft(){if(state.session)localStorage.setItem('draft:'+state.session,$('question').value);}
const imageDrafts=new Map();
let pasteQueue=Promise.resolve(),pastePending=0;
function pastedImages(){return imageDrafts.get(state.session)||[];}
function renderPastedImages(){
  const area=$('pasted-images');area.replaceChildren();const images=pastedImages();area.hidden=!images.length;
  for(const item of images){
    const card=document.createElement('div');card.className='pasted-image';
    const img=document.createElement('img');img.src=item.data;img.alt='待发送图片';
    const remove=document.createElement('button');remove.type='button';remove.className='remove-image';remove.textContent='×';remove.title='移除此图片';remove.setAttribute('aria-label','移除此图片');
    remove.onclick=()=>{imageDrafts.set(state.session,pastedImages().filter(i=>i.id!==item.id));renderPastedImages();$('question').focus();};
    card.append(img,remove);area.append(card);
  }
  if(images.length){const hint=document.createElement('span');hint.className='pasted-hint';hint.textContent=`待发送 ${images.length}/4 · 需图片模型`;area.append(hint);}
}
async function clipboardImage(file){
  if(file.size>32*1024*1024)throw Error('图片过大，请缩小截图后粘贴');
  const bitmap=await createImageBitmap(file);
  try{
    const scale=Math.min(1,2000/bitmap.width,2000/bitmap.height);const canvas=document.createElement('canvas');
    canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
    canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);return canvas.toDataURL('image/png');
  }finally{bitmap.close();}
}
bind('question','paste',event=>{
  const files=Array.from(event.clipboardData?.items||[]).filter(item=>item.kind==='file'&&item.type.startsWith('image/')).map(item=>item.getAsFile()).filter(Boolean);
  if(!files.length)return;event.preventDefault();const sid=state.session;if(!sid)return;
  const text=event.clipboardData.getData('text/plain');if(text){const q=$('question');q.setRangeText(text,q.selectionStart,q.selectionEnd,'end');saveDraft();}
  ++pastePending;
  pasteQueue=pasteQueue.then(async()=>{
    const existing=imageDrafts.get(sid)||[];if(existing.length+files.length>4)throw Error('每条问题最多粘贴 4 张图片，可先移除不需要的图片');
    const added=[];for(const file of files)added.push({id:crypto.randomUUID(),data:await clipboardImage(file)});
    // Existing drafts may have been removed while decoding the clipboard image.
    const current=imageDrafts.get(sid)||[];
    if([...current,...added].reduce((sum,item)=>sum+(item.data.length-22)*.75,0)>8*1024*1024)throw Error('粘贴图片总大小不能超过 8MB，请缩小图片后重试');
    imageDrafts.set(sid,[...current,...added]);if(sid===state.session)renderPastedImages();
  }).catch(error=>toast(error.message||'图片无法读取，请重新截图后粘贴')).finally(()=>--pastePending);
});
async function loadMessages(){
  if(!state.session)return;const sid=state.session;const data=await api('messages?session='+sid);if(sid!==state.session)return;
  state.messageRows=data.messages;renderMessages();renderPastedImages();$('question').value=localStorage.getItem('draft:'+sid)||'';
  if(data.active)trackJob(data.active);else setBusy(false);
}
function setBusy(busy){$('send-question').disabled=busy;$('stop-answer').hidden=!busy;if(!busy){state.job=null;$('chat-status').textContent='';}}
async function trackJob(job){
  const poll=++state.polling;state.job=job;setBusy(true);const sid=state.session;
  $('chat-status').textContent=`${job.model} · 正在回答…`;
  while(poll===state.polling&&sid===state.session&&!$('reader').hidden){
    try {
      const current=await api('job?id='+job.id);if(poll!==state.polling||sid!==state.session)return;
      state.job=current;
      const area=$('messages');const bottom=area.scrollHeight-area.scrollTop-area.clientHeight<100;
      let row=state.messageRows.find(m=>m.id===current.messageId);
      if(row){Object.assign(row,{content:current.text,status:current.status,error:current.error});const old=area.querySelector(`[data-message="${current.messageId}"]`);if(old)old.replaceWith(renderMessage(row));}
      if(bottom)area.scrollTop=area.scrollHeight;
      const s=current.stats;$('chat-status').textContent=`${current.status==='streaming'?'正在回答 · ':''}本次使用最近 ${s.historyTurns}/${s.totalTurns} 轮 · 历史全文已保存`;
      if(current.status!=='streaming'){setBusy(false);if(current.error)toast(current.error);state.book=await api('book?id='+state.book.id);renderSessions();return;}
    }catch(error){if(poll===state.polling){setBusy(false);toast(error.message);}return;}
    await new Promise(resolve=>setTimeout(resolve,350));
  }
}
bind('session-select','change',async()=>{saveDraft();++state.polling;state.job=null;state.session=$('session-select').value;await api('session/select',{bookId:state.book.id,sessionId:state.session});setContext(null);await loadMessages();});
bind('new-session','click',async()=>{saveDraft();++state.polling;const s=await api('session/new',{bookId:state.book.id});state.session=s.id;state.book=await api('book?id='+state.book.id);renderSessions();setContext(null);await loadMessages();});
bind('rename-session','click',async()=>{const s=state.book.sessions.find(s=>s.id===state.session);const title=prompt('会话名称',s.title);if(!title?.trim())return;await api('session/rename',{sessionId:state.session,title});s.title=title;renderSessions();});
bind('export-session','click',async()=>{if(window.pywebview?.api){if(await window.pywebview.api.export_session(state.session))toast('会话与引用截图已导出');}else{const a=document.createElement('a');a.href='api/export?session='+state.session;a.download='StudyRead-conversation.zip';a.click();}});
bind('question','input',saveDraft);
bind('question','keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!$('send-question').disabled)$('ask-form').requestSubmit();}});
bind('ask-form','submit',async e=>{
  e.preventDefault();if(pastePending){toast('正在读取剪贴板图片，请稍候再发送');return;}
  const images=[...pastedImages()],typed=$('question').value.trim();const question=typed||(images.length?'请解释图片中的内容，结合当前阅读上下文说明。':'');if(!question)return;
  if(!activeProfile()?.hasKey){openSettings();toast('请先配置模型，也可导入刊读现有配置');return;}
  if((state.selected?.rect||$('attach-page').checked||images.length)&&!activeProfile().vision){openSettings();toast('图片提问需要支持图片的模型');return;}
  const payload={sessionId:state.session,question,page:state.selected?.page||currentPage(),selection:state.selected?.text||'',rect:state.selected?.rect||null,attachImage:$('attach-page').checked,images:images.map(i=>i.data)};
  $('send-question').disabled=true;
  try{
    await api('ask',payload);const sent=new Set(images.map(i=>i.id));imageDrafts.set(payload.sessionId,(imageDrafts.get(payload.sessionId)||[]).filter(i=>!sent.has(i.id)));
    if(state.session!==payload.sessionId)return;
    if($('question').value.trim()===typed){$('question').value='';saveDraft();}
    renderPastedImages();setContext(null);$('attach-page').checked=false;await loadMessages();
  }catch(error){if(state.session===payload.sessionId)setBusy(false);throw error;}
});
bind('stop-answer','click',async()=>{if(state.job){await api('cancel',{id:state.job.id});$('chat-status').textContent='正在停止，部分回答会保留…';}});

let profileDrafts=[],profileIndex=-1;
function openSettings(){profileDrafts=structuredClone(state.settings.profiles||[]);profileIndex=profileDrafts.findIndex(p=>p.id===state.settings.activeProfile);if(profileIndex<0)profileIndex=0;renderProfileList();$('settings-result').textContent='';$('settings-dialog').showModal();}
document.querySelectorAll('.settings-open').forEach(btn=>btn.onclick=openSettings);
function renderProfileList(){$('profile-select').replaceChildren();profileDrafts.forEach((p,i)=>$('profile-select').add(new Option(p.name||'新配置',String(i))));$('profile-select').value=String(profileIndex);$('profile-fields').hidden=!profileDrafts.length;$('delete-profile').disabled=!profileDrafts.length;fillProfile();}
function fillProfile(){const p=profileDrafts[profileIndex]||{};for(const [field,key]of [['name','name'],['provider','provider'],['url','baseUrl'],['model','model']])$('profile-'+field).value=p[key]||(key==='provider'?'openai':'');$('profile-key').value=p.apiKey||'';$('profile-key').placeholder=p.hasKey?'密钥已保存，留空保持不变':'填写 API Key';$('profile-vision').checked=!!p.vision;}
function collectProfile(){const p=profileDrafts[profileIndex];if(!p)return;Object.assign(p,{name:$('profile-name').value,provider:$('profile-provider').value,baseUrl:$('profile-url').value,model:$('profile-model').value,apiKey:$('profile-key').value,vision:$('profile-vision').checked});}
bind('settings-close','click',()=>$('settings-dialog').close());
bind('profile-select','change',()=>{collectProfile();profileIndex=Number($('profile-select').value);fillProfile();});
bind('add-profile','click',()=>{collectProfile();profileDrafts.push({id:crypto.randomUUID().replaceAll('-',''),name:'新配置',provider:'openai',baseUrl:'https://api.deepseek.com',model:'deepseek-chat',vision:false});profileIndex=profileDrafts.length-1;renderProfileList();});
bind('delete-profile','click',()=>{profileDrafts.splice(profileIndex,1);profileIndex=Math.max(0,profileIndex-1);renderProfileList();});
async function persistSettings(){collectProfile();state.settings=await api('settings',{profiles:profileDrafts,activeProfile:profileDrafts[profileIndex]?.id||''});updateModel();}
bind('save-settings','click',async()=>{try{await persistSettings();$('settings-dialog').close();toast('模型配置已保存');}catch(error){$('settings-result').textContent=error.message;}});
bind('test-model','click',async()=>{try{await persistSettings();$('test-model').disabled=true;$('settings-result').textContent='正在测试…';const data=await api('settings/test',{});$('settings-result').textContent='连接成功：'+data.reply;}catch(error){$('settings-result').textContent=error.message;}finally{$('test-model').disabled=false;}});
bind('import-kandu','click',async()=>{try{state.settings=await api('settings/import',{});updateModel();profileDrafts=structuredClone(state.settings.profiles);profileIndex=profileDrafts.findIndex(p=>p.id===state.settings.activeProfile);renderProfileList();$('settings-result').textContent='已导入本机刊读配置。图片能力请按模型实际情况勾选。';}catch(error){$('settings-result').textContent=error.message;}});
bind('open-data','click',()=>window.pywebview?.api.open_data_folder());
let dragDivider=false;
$('chat-divider').addEventListener('pointerdown',e=>{dragDivider=true;$('chat-divider').setPointerCapture(e.pointerId);});
$('chat-divider').addEventListener('pointermove',e=>{if(!dragDivider)return;const width=Math.max(320,Math.min(innerWidth*.55,innerWidth-e.clientX));document.documentElement.style.setProperty('--chat-width',width+'px');});
$('chat-divider').addEventListener('pointerup',()=>{dragDivider=false;localStorage.setItem('chat-width',getComputedStyle(document.documentElement).getPropertyValue('--chat-width'));if(state.doc&&$('pdf-zoom').value==='width')viewer.currentScaleValue='page-width';});
if(localStorage.getItem('chat-width'))document.documentElement.style.setProperty('--chat-width',localStorage.getItem('chat-width'));
await refreshLibrary().catch(error=>toast('启动失败：'+error.message));
