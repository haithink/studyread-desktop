"""Reproducible Windows folder release including local frontend assets and licenses."""
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))
from studyread import __version__

assets = repo / 'studyread/web'
if not (assets/'vendor/pdfjs/build/pdf.mjs').is_file():
    raise SystemExit('Run npm ci --omit=optional --ignore-scripts && npm run vendor first')
version = tuple(map(int, __version__.split('.'))) + (0,)
version_file = repo / 'ver.txt'
version_file.write_text(f'''VSVersionInfo(ffi=FixedFileInfo(filevers={version!r},prodvers={version!r},
mask=0x3f,flags=0,OS=0x40004,fileType=0x1,subtype=0,date=(0,0)),kids=[
StringFileInfo([StringTable('080404b0',[
StringStruct('CompanyName','haithink'),StringStruct('FileDescription','StudyRead - PDF learning companion'),
StringStruct('FileVersion','{__version__}'),StringStruct('ProductName','StudyRead'),
StringStruct('ProductVersion','{__version__}')])]),VarFileInfo([VarStruct('Translation',[2052,1200])])])''',encoding='utf-8')
command = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
           '--name','StudyRead','--distpath',str(repo/'dist'/('v'+__version__)),
           '--workpath',str(repo/'build'/('v'+__version__)), '--specpath',str(repo/'build'),
           '--version-file',str(version_file),'--icon',str(assets/'icon.ico'),
           '--add-data',str(assets)+';studyread/web','--collect-all','webview',
           '--collect-all','pythonnet','--collect-all','clr_loader',
           '--exclude-module','PyQt5','--exclude-module','PyQt6','--exclude-module','PySide6',
           '--exclude-module','gtk','--exclude-module','cefpython3']
# Conda-based Python needs its SQLite/zlib DLLs explicitly present in the bundle.
conda_dlls = Path(sys.base_prefix)/'Library/bin'
for name in ('sqlite3.dll','zlib.dll','zlib-ng2.dll','libffi-8.dll'):
    if (conda_dlls/name).is_file():
        command += ['--add-binary',str(conda_dlls/name)+';.']
for package in ('pywebview','pythonnet','clr_loader','cffi','requests','urllib3','certifi','PyMuPDF','bottle','proxy_tools'):
    command += ['--copy-metadata',package]
command.append(str(repo/'main.py'))
subprocess.run(command,cwd=repo,check=True)
release = repo/'dist'/('v'+__version__)/'StudyRead'
for name in ('README.md','DESIGN.md','LICENSE','THIRD_PARTY_NOTICES.md','requirements-lock.txt','package-lock.json'):
    shutil.copy2(repo/name,release/name)
shutil.copytree(repo/'LICENSES',release/'LICENSES',dirs_exist_ok=True)
shutil.copytree(repo/'docs',release/'docs',dirs_exist_ok=True)
archive = repo/'dist'/f'StudyRead-v{__version__}-win64.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for path in sorted(release.rglob('*')):
        if path.is_file():
            z.write(path,Path('StudyRead')/path.relative_to(release))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
print('RELEASE:',release/'StudyRead.exe')
print('ARCHIVE:',archive,archive.stat().st_size,'bytes')
