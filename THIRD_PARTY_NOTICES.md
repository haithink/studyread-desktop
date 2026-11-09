# 第三方资源

理读的原创代码采用 AGPL-3.0-only。第三方依赖保留其上游版权和许可声明。

| 组件 | 用途 | 固定资源或声明 |
| --- | --- | --- |
| PyMuPDF 1.24.14 | 封面、目录、按页文字提取、区域截图 | AGPL 开源许可，副本见 `LICENSES/PyMuPDF-COPYING.txt` |
| PDF.js 6.5.438 | 原版 PDF 的前端渲染、文字选择、搜索与链接 | Mozilla / Apache-2.0，`LICENSES/PDFJS-Apache-2.0.txt` |
| KaTeX 0.19.1 | 数学公式排版 | MIT，`LICENSES/KaTeX-MIT.txt`；字体和资源的原始声明随 vendor 保留 |
| Marked 18.1.3 | Markdown | MIT，`LICENSES/Marked-MIT.txt` |
| DOMPurify 3.4.17 | 回答 HTML 清理 | Apache-2.0 / MPL-2.0，`LICENSES/DOMPurify.txt` |
| pywebview 6.2.1 | Windows WebView2 桌面窗口 | BSD-3-Clause，`LICENSES/pywebview-BSD.txt` |

前端资源由 `package-lock.json` 固定，通过 `npm ci --omit=optional --ignore-scripts` 和 `npm run vendor`
复制进 `studyread/web/vendor`。PDF.js 的 WebAssembly 编解码器、标准字体、CMap、图标等目录保留
其原有 LICENSE 文件；这些文件与软件一并分发。

Requests、urllib3、certifi、pythonnet、clr_loader、cffi、Bottle、Python、SQLite、PyInstaller 等运行或构建
组件按各自上游许可证使用。Windows WebView2 Runtime 由 Microsoft 单独分发，免安装包不包含该运行时。
`requirements-lock.txt` 记录本版本构建环境，打包时通过 PyInstaller 元数据保留所用组件的许可文件。

教材 PDF、用户提问、模型回答和 API 密钥是本机用户数据，不包含在源码或发行包中。
软件图标为本项目用 SVG / 绘图代码创建的书本与积分符号，生成脚本在 `tools/build_icon.py`。
