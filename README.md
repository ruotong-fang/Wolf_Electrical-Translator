# Wolf Electrical Translator

面向 Windows 的本地离线电气工程中英翻译工具。

## 当前功能

- 中英双向快速翻译，使用本地 Argos/CTranslate2 模型
- 专业翻译模式，使用本地 Qwen GGUF 模型进行受控润色
- 保护电压、电流、单位、IEC/IEEE 等标准号和设备编号
- 约 1200 条分领域电气术语与固定短语，支持 CSV 导入导出
- 翻译记忆：保存审核译文，复用相同或高度相似句段
- 打开 TXT、文本型 PDF、DOCX、XLSX
- TXT 编码识别与预览，支持 UTF-8、UTF-16、GB18030、Big5 和 Windows ANSI
- 保存译文为 UTF-8 文本
- 原文、译文、术语、记忆和模型推理均保留在本机

扫描 PDF OCR、DWG/DXF 图纸解析和原版式回写暂未实现。

## 最终用户

最终用户只会收到一个文件：

```text
Wolf-Electrical-Translator-Setup-0.2.0.exe
```

双击安装后即可离线使用，不需要安装 Python、下载模型、配置环境或运行 BAT 文件。安装包包含：

- Python 解释器与全部依赖
- 应用代码和 Windows 桌面界面
- 中英双向 Argos 模型
- Qwen2.5 1.5B Q4_K_M 本地模型
- llama.cpp Windows CPU 运行时
- 内置术语和翻译记忆数据库结构

安装包预计约 1.3–1.8GB，实际大小以 Windows 构建结果为准。

## Windows 发布构建

以下要求只适用于开发者构建电脑：

1. Windows 10/11 64 位
2. 64 位 Python 3.11
3. Inno Setup 6
4. 首次构建时可访问 Python 包仓库、Argos、Hugging Face 和 GitHub

开发者双击：

```text
build_release_windows.bat
```

脚本会自动创建隔离环境、安装依赖、下载并校验全部模型和 llama.cpp、运行测试、封装 Python 应用，最终生成：

```text
installer-output\Wolf-Electrical-Translator-Setup-0.2.0.exe
```

也可以在 GitHub Actions 页面运行 `Build Windows Installer`，完成后下载 `EE-Translator-Windows-Installer` artifact。目标电脑安装和运行时不需要联网。

完整的安装、使用和 Windows 验收步骤见 [WINDOWS使用教程.md](WINDOWS使用教程.md)。

## 专业翻译

快速翻译使用 Argos。专业翻译会继续调用安装包内置的 Qwen2.5 1.5B Q4_K_M 和 llama.cpp CPU 运行时。应用保留了选择其他 GGUF 模型的能力；专业模型发生错误或修改了工程参数时，会安全回退到快速翻译结果。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.smoke_test_models
```
