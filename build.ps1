$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if (Get-Command "py" -ErrorAction SilentlyContinue) {
    $BootstrapPython = "py"
    $BootstrapArgs = @("-3.11")
} elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    $BootstrapPython = "python"
    $BootstrapArgs = @()
} else {
    throw "未找到 Python 3.11。仅构建电脑需要安装，最终用户不需要。"
}

$BootstrapVersion = & $BootstrapPython @BootstrapArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($BootstrapVersion -ne "3.11") {
    throw "构建需要 Python 3.11，当前检测到 $BootstrapVersion。最终用户不需要安装 Python。"
}

if (-not (Test-Path -LiteralPath $Python)) {
    & $BootstrapPython @BootstrapArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        throw "无法创建 Python 3.11 环境。请确认已安装 64 位 Python 3.11。"
    }
}

$Version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($Version -ne "3.11") {
    throw ".venv 使用的是 Python $Version。请删除 .venv 后重新运行。"
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "依赖安装失败。"
}

$ModelDir = Join-Path $Root "models"
New-Item -ItemType Directory -Path $ModelDir -Force | Out-Null
$Models = @(
    @{
        Name = "translate-en_zh-1_9.argosmodel"
        Url = "https://argos-net.com/v1/translate-en_zh-1_9.argosmodel"
        Hash = "433E7C4F034D87FBE2353161E05F18646D7999452F801A4E1F0378522B9850AB"
    },
    @{
        Name = "translate-zh_en-1_9.argosmodel"
        Url = "https://argos-net.com/v1/translate-zh_en-1_9.argosmodel"
        Hash = "62E7AF5A3A48B530E47B7B3E5C78C2DE79073ECD815750D2BF3AB35B4A67DA2D"
    }
)
foreach ($Model in $Models) {
    $Path = Join-Path $ModelDir $Model.Name
    $Valid = (Test-Path -LiteralPath $Path) -and ((Get-FileHash $Path -Algorithm SHA256).Hash -eq $Model.Hash)
    if (-not $Valid) {
        Write-Host "正在下载离线模型：$($Model.Name)"
        Invoke-WebRequest -Uri $Model.Url -OutFile $Path
    }
    if ((Get-FileHash $Path -Algorithm SHA256).Hash -ne $Model.Hash) {
        throw "模型校验失败：$($Model.Name)"
    }
}

$LlmDir = Join-Path $Root "llm"
New-Item -ItemType Directory -Path $LlmDir -Force | Out-Null
$LlmName = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
$LocalModel = Join-Path $LlmDir $LlmName
$LlmHash = "6A1A2EB6D15622BF3C96857206351BA97E1AF16C30D7A74EE38970E434E9407E"
$LlmValid = (Test-Path -LiteralPath $LocalModel) -and ((Get-FileHash $LocalModel -Algorithm SHA256).Hash -eq $LlmHash)
if (-not $LlmValid) {
    Write-Host "正在下载本地专业润色模型（约 1.12 GB，请耐心等待）..."
    Invoke-WebRequest `
        -Uri "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true" `
        -OutFile $LocalModel
}
if ((Get-FileHash $LocalModel -Algorithm SHA256).Hash -ne $LlmHash) {
    throw "Qwen GGUF 模型校验失败。"
}

$RuntimeDir = Join-Path $Root "runtime"
$CacheDir = Join-Path $Root ".build-cache"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
$RuntimeZip = Join-Path $CacheDir "llama-b9750-bin-win-cpu-x64.zip"
$RuntimeHash = "A6E59DF3F054D82EBC873AC40998BE916F7532B7FF13E970DD86A66F08974D20"
$RuntimeZipValid = (Test-Path -LiteralPath $RuntimeZip) -and ((Get-FileHash $RuntimeZip -Algorithm SHA256).Hash -eq $RuntimeHash)
if (-not $RuntimeZipValid) {
    Write-Host "正在下载 llama.cpp Windows CPU 运行时..."
    Invoke-WebRequest `
        -Uri "https://github.com/ggml-org/llama.cpp/releases/download/b9750/llama-b9750-bin-win-cpu-x64.zip" `
        -OutFile $RuntimeZip
}
if ((Get-FileHash $RuntimeZip -Algorithm SHA256).Hash -ne $RuntimeHash) {
    throw "llama.cpp 运行时校验失败。"
}
Expand-Archive -LiteralPath $RuntimeZip -DestinationPath $RuntimeDir -Force
$LlamaCli = Get-ChildItem -Path $RuntimeDir -Filter "llama-cli.exe" -File -Recurse | Select-Object -First 1
if (-not $LlamaCli) {
    throw "llama.cpp 压缩包中未找到 llama-cli.exe。"
}
if ($LlamaCli.DirectoryName -ne $RuntimeDir) {
    Copy-Item -Path (Join-Path $LlamaCli.DirectoryName "*") -Destination $RuntimeDir -Recurse -Force
}

& $Python -m unittest discover -s (Join-Path $Root "tests") -v
if ($LASTEXITCODE -ne 0) {
    throw "自动测试失败，已停止构建。"
}

$env:ARGOS_PACKAGES_DIR = Join-Path $Root ".build-test\packages"
$env:XDG_DATA_HOME = Join-Path $Root ".build-test\data"
$env:XDG_CONFIG_HOME = Join-Path $Root ".build-test\config"
$env:XDG_CACHE_HOME = Join-Path $Root ".build-test\cache"
& $Python -m scripts.smoke_test_models
if ($LASTEXITCODE -ne 0) {
    throw "离线翻译模型验证失败，已停止构建。"
}

$CTranslateDir = & $Python -c "import pathlib, ctranslate2; print(pathlib.Path(ctranslate2.__file__).parent)"
$Arguments = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onedir", "--noconsole",
    "--name", "EETranslator",
    "--paths", $Root,
    "--add-data", "${Root}\runtime;runtime",
    "--add-data", "${Root}\models;models",
    "--hidden-import", "argostranslate.package",
    "--hidden-import", "argostranslate.settings",
    "--hidden-import", "argostranslate.tokenizer",
    "--hidden-import", "argostranslate.networking",
    "--hidden-import", "argostranslate.utils",
    "--hidden-import", "ctranslate2",
    "--hidden-import", "ctranslate2._ext",
    "--collect-all", "sentencepiece",
    "--collect-all", "openpyxl",
    "--collect-all", "pypdf",
    "--collect-all", "docx",
    "--exclude-module", "torch",
    "--exclude-module", "stanza",
    "--exclude-module", "spacy",
    "--exclude-module", "minisbd",
    "--exclude-module", "onnxruntime",
    "--exclude-module", "tensorflow",
    "--exclude-module", "pandas",
    (Join-Path $Root "launcher.py")
)

foreach ($Dll in ("ctranslate2.dll", "libiomp5md.dll")) {
    $DllPath = Join-Path $CTranslateDir $Dll
    if (Test-Path -LiteralPath $DllPath) {
        $Arguments += @("--add-binary", "${DllPath};ctranslate2")
    }
}

$Arguments += @("--add-data", "${LocalModel};llm")

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $Root "README.txt") -Destination (Join-Path $Root "dist\EETranslator\README.txt") -Force
Copy-Item -LiteralPath (Join-Path $Root "THIRD_PARTY_NOTICES.txt") -Destination (Join-Path $Root "dist\EETranslator\THIRD_PARTY_NOTICES.txt") -Force

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "未找到 Inno Setup 6。开发机安装后重新运行即可生成最终安装包。"
}
& $Iscc (Join-Path $Root "installer.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup 安装包生成失败。"
}

$Installer = Join-Path $Root "installer-output\Wolf-Electrical-Translator-Setup-0.2.0.exe"
$InstallerHash = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "${Installer}.sha256" -Value "$InstallerHash  Wolf-Electrical-Translator-Setup-0.2.0.exe" -Encoding ascii
Write-Host "发布包构建完成：$Installer"
Write-Host "SHA-256：$InstallerHash"
