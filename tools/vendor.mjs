import { mkdir, copyFile, cp, readdir } from 'node:fs/promises';
import path from 'node:path';
const root = new URL('../', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const dest = path.join(root, 'studyread/web/vendor');
await mkdir(dest, { recursive: true });
const pairs = [
 ['pdfjs-dist/LICENSE','PDFJS-LICENSE'], ['katex/dist/katex.min.js','katex.min.js'],
 ['katex/dist/katex.min.css','katex.min.css'], ['katex/LICENSE','KATEX-LICENSE'],
 ['marked/lib/marked.umd.js','marked.js'], ['marked/LICENSE','MARKED-LICENSE'],
 ['dompurify/dist/purify.min.js','purify.min.js'], ['dompurify/LICENSE','DOMPURIFY-LICENSE']
];
for(const [src,name] of pairs) await copyFile(path.join(root,'node_modules',src),path.join(dest,name));
for(const dir of ['build','web']) {
 await mkdir(path.join(dest,'pdfjs',dir),{recursive:true});
 for(const name of await readdir(path.join(root,'node_modules/pdfjs-dist',dir))) {
  if(name.endsWith('.mjs')||name.endsWith('.css')) await copyFile(path.join(root,'node_modules/pdfjs-dist',dir,name),path.join(dest,'pdfjs',dir,name));
 }
}
for(const dir of ['cmaps','standard_fonts','wasm','web/images']) await cp(path.join(root,'node_modules/pdfjs-dist',dir),path.join(dest,'pdfjs',dir),{recursive:true});
await cp(path.join(root,'node_modules/katex/dist/fonts'),path.join(dest,'fonts'),{recursive:true});
console.log('Offline PDF, math and Markdown assets copied to studyread/web/vendor');
