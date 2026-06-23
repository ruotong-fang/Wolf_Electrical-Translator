# Wolf Electrical Translator Windows 使用教程

## 一、下载完整安装包

### 从 GitHub Actions 下载

1. 打开项目的 GitHub 页面。
2. 点击顶部 `Actions`。
3. 选择左侧 `Build Windows Installer`。
4. 打开最新一次绿色、状态为成功的运行记录。
5. 在页面底部 `Artifacts` 中下载 `EE-Translator-Windows-Installer`。
6. 解压下载的 ZIP，得到：

```text
Wolf-Electrical-Translator-Setup-0.2.1.exe
Wolf-Electrical-Translator-Setup-0.2.1.exe.sha256
```

安装包已经包含 Python、应用依赖、双向翻译模型、Qwen 本地大模型和 llama.cpp，无需另外下载组件。

## 二、校验安装包

在安装包所在文件夹空白处按住 `Shift` 并点击鼠标右键，选择“在终端中打开”，运行：

```powershell
Get-FileHash .\Wolf-Electrical-Translator-Setup-0.2.1.exe -Algorithm SHA256
Get-Content .\Wolf-Electrical-Translator-Setup-0.2.1.exe.sha256
```

两个命令显示的哈希值应完全一致。如果不一致，不要安装，重新下载安装包。

## 三、安装

1. 双击 `Wolf-Electrical-Translator-Setup-0.2.1.exe`。
2. 当前测试版尚未购买代码签名证书，Windows 可能显示 SmartScreen 提示。
3. 确认文件哈希正确后，点击“更多信息”，再点击“仍要运行”。
4. 按安装向导继续，建议保留默认安装位置。
5. 勾选“创建桌面快捷方式”。
6. 安装结束后点击“启动电气工程翻译器”。

安装不需要管理员权限，也不需要安装 Python。

## 四、首次启动

第一次启动会把内置 Argos 模型展开到当前 Windows 用户的数据目录，可能比后续启动稍慢。等待底部状态栏出现：

```text
快速翻译引擎已就绪；本地专业润色已就绪
```

程序和模型均在本机运行。安装完成后可以断开网络再进行涉密材料测试。

## 五、文本翻译

1. 在“翻译”页面选择“英文 → 中文”或“中文 → 英文”。
2. 将原文粘贴到左侧文本框。
3. 选择翻译模式：
   - `快速翻译`：使用 Argos，启动和翻译速度较快。
   - `专业翻译`：先快速翻译，再使用本地 Qwen 模型改善工程表达，普通 CPU 首次运行可能需要较长时间。
4. 点击“开始翻译”。
5. 右侧可在“最终译文”和“ARGOS 初译”之间切换对比。
6. 人工确认并修改译文后，点击“记住此译文”，以后会优先复用审核结果。
7. 点击“保存译文”可导出 UTF-8 文本文件。

## 六、文件翻译

点击“打开文件”，当前支持：

- TXT
- 文本型 PDF
- DOCX
- XLSX

TXT 支持 UTF-8、UTF-16、GB18030、Big5 和 Windows ANSI；编码不确定时会显示预览供选择。

当前版本尚不支持：

- 扫描 PDF OCR
- DWG/DXF 图纸解析
- 保留原 PDF、Word 或 Excel 版式导出

文件功能目前是“提取文字 → 翻译 → 保存为 TXT”。

## 七、术语与翻译记忆

### 术语与短语

- 可以添加中英文术语、分类、领域、优先级和备注。
- 固定短语和高优先级术语会优先匹配。
- 支持 CSV 导入和导出。

### 翻译记忆

- “记住此译文”会按句段保存人工确认结果。
- 完全相同的原文会直接复用。
- 高度相似且工程参数一致的句段可被复用或提示参考。

## 八、本地数据位置

用户术语、翻译记忆、设置和已展开的 Argos 模型位于：

```text
%LOCALAPPDATA%\EETranslator
```

默认不会把原文或译文发送到网络。不要把用户数据目录加入云盘同步。

## 九、建议的验收测试

1. 安装后断开网络，确认程序仍能启动并完成双向翻译。
2. 测试以下工程参数是否原样保留：`11 kV`、`630 A`、`IEC 62271`、`IP65`。
3. 分别测试快速翻译和专业翻译。
4. 测试 TXT、文本型 PDF、DOCX 和 XLSX。
5. 修改译文并点击“记住此译文”，再次翻译相同原文，确认命中翻译记忆。
6. 关闭并重新打开程序，确认术语和翻译记忆仍在。
7. 在“设置 → 应用 → 已安装的应用”中卸载，确认卸载流程正常。

建议测试句：

```text
The vacuum circuit breaker rated voltage is 11 kV according to IEC 62271.
```

预期要求：`真空断路器`、`11 kV` 和 `IEC 62271` 必须完整保留。

## 十、问题排查

- 启动失败日志：`%USERPROFILE%\EETranslator-error.log`
- 专业翻译较慢：属于 CPU 本地模型的正常现象，可先使用快速翻译。
- 专业译文丢失参数：程序应自动退回 ARGOS 初译，并在底部状态栏显示警告。
- 安装包无法启动：先重新核对 SHA-256，再记录 Windows 版本和报错截图。
