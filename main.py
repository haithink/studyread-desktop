"""理读 · StudyRead 桌面入口。--serve 仅供浏览器开发与自动化验证。"""
import argparse
import os
from pathlib import Path
import sys
import threading

from studyread import __version__, config, store
from studyread.server import ApplicationServer, export_zip


class NativeBridge:
    _window = None

    def choose_files(self):
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                              file_types=('PDF files (*.pdf)',))
        return list(paths or [])

    def export_session(self, session_id):
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename='StudyRead-conversation.zip',
                                              file_types=('ZIP archive (*.zip)',))
        if not paths:
            return False
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        Path(path).write_bytes(export_zip(session_id))
        return True

    def open_data_folder(self):
        if sys.platform == 'win32':
            os.startfile(config.data_dir())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pdf', nargs='?')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    # 锁定本数据目录，防止两份程序把对方正在生成的回答标为中断。
    lock = (config.data_dir() / 'app.lock').open('a+b')
    if sys.platform == 'win32':
        import msvcrt
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, '理读已在运行，请切换到已有窗口。', '理读 · StudyRead', 0)
            return
    server = ApplicationServer()
    if args.pdf:
        store.add_book(args.pdf)
    server.start()
    try:
        if args.serve:
            print(server.url, flush=True)
            threading.Event().wait()
        else:
            import webview
            bridge = NativeBridge()
            bridge._window = webview.create_window(f'理读 · StudyRead v{__version__}', server.url,
                                                  js_api=bridge, width=1440, height=940, min_size=(1000, 680))
            webview.start(gui='edgechromium', debug=args.debug,
                          icon=str(Path(__file__).resolve().parent / 'studyread' / 'web' / 'icon.ico'),
                          storage_path=str(config.data_dir() / 'webview'), private_mode=True)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        lock.close()


if __name__ == '__main__':
    main()
