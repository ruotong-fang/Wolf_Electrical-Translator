$ErrorActionPreference = "Stop"
$Python = "D:\vscoder\py313\python.exe"
$LocalModel = "$env:LOCALAPPDATA\EETranslator\llm\qwen2.5-1.5b-instruct-q4_k_m.gguf"
$CTranslateDir = "D:\vscoder\py313\Lib\site-packages\ctranslate2"

if (-not (Test-Path -LiteralPath $LocalModel)) {
    throw "未找到本地润色模型：$LocalModel"
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --noconsole `
    --name "EETranslator" `
    --add-data "$PSScriptRoot\runtime;runtime" `
    --add-data "$PSScriptRoot\models;models" `
    --add-data "$LocalModel;llm" `
    --hidden-import argostranslate.package `
    --hidden-import argostranslate.settings `
    --hidden-import argostranslate.tokenizer `
    --hidden-import argostranslate.networking `
    --hidden-import argostranslate.utils `
    --hidden-import ctranslate2 `
    --hidden-import ctranslate2._ext `
    --add-binary "$CTranslateDir\ctranslate2.dll;ctranslate2" `
    --add-binary "$CTranslateDir\libiomp5md.dll;ctranslate2" `
    --collect-all sentencepiece `
    --collect-all openpyxl `
    --collect-all pypdf `
    --collect-all docx `
    --exclude-module torch `
    --exclude-module stanza `
    --exclude-module spacy `
    --exclude-module minisbd `
    --exclude-module onnxruntime `
    --exclude-module tensorflow `
    --exclude-module keras `
    --exclude-module pandas `
    --exclude-module scipy `
    --exclude-module matplotlib `
    --exclude-module h5py `
    --exclude-module IPython `
    --exclude-module pygments `
    --exclude-module jedi `
    --exclude-module zmq `
    --exclude-module pkg_resources `
    "$PSScriptRoot\launcher.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

Copy-Item -LiteralPath "$PSScriptRoot\README.txt" -Destination "$PSScriptRoot\dist\EETranslator\README.txt" -Force

Write-Host "构建完成：$PSScriptRoot\dist\EETranslator\EETranslator.exe"
