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
    throw "Python 3.11 not found. It is only required on the build machine, not for end users."
}

$BootstrapVersion = & $BootstrapPython @BootstrapArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($BootstrapVersion -ne "3.11") {
    throw "Build requires Python 3.11, but detected $BootstrapVersion. End users do not need Python installed."
}

if (-not (Test-Path -LiteralPath $Python)) {
    & $BootstrapPython @BootstrapArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Python 3.11 virtual environment. Please make sure 64-bit Python 3.11 is installed."
    }
}

$Version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($Version -ne "3.11") {
    throw "The .venv is using Python $Version. Please delete .venv and run this script again."
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
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
        Write-Host "Downloading offline translation model: $($Model.Name)"
        Invoke-WebRequest -Uri $Model.Url -OutFile $Path
    }
    if ((Get-FileHash $Path -Algorithm SHA256).Hash -ne $Model.Hash) {
        throw "Model verification failed: $($Model.Name)"
    }
}

$LlmDir = Join-Path $Root "llm"
New-Item -ItemType Directory -Path $LlmDir -Force | Out-Null
$LlmName = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
$LocalModel = Join-Path $LlmDir $LlmName
$LlmHash = "6A1A2EB6D15622BF3C96857206351BA97E1AF16C30D7A74EE38970E434E9407E"
$LlmValid = (Test-Path -LiteralPath $LocalModel) -and ((Get-FileHash $LocalModel -Algorithm SHA256).Hash -eq $LlmHash)
if (-not $LlmValid) {
    Write-Host "Downloading local polishing model, about 1.12 GB. Please wait..."
    Invoke-WebRequest `
        -Uri "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true" `
        -OutFile $LocalModel
}
if ((Get-FileHash $LocalModel -Algorithm SHA256).Hash -ne $LlmHash) {
    throw "Qwen GGUF model verification failed."
}

$RuntimeDir = Join-Path $Root "runtime"
$CacheDir = Join-Path $Root ".build-cache"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
$RuntimeZip = Join-Path $CacheDir "llama-b9750-bin-win-cpu-x64.zip"
$RuntimeHash = "A6E59DF3F054D82EBC873AC40998BE916F7532B7FF13E970DD86A66F08974D20"
$RuntimeZipValid = (Test-Path -LiteralPath $RuntimeZip) -and ((Get-FileHash $RuntimeZip -Algorithm SHA256).Hash -eq $RuntimeHash)
if (-not $RuntimeZipValid) {
    Write-Host "Downloading llama.cpp Windows CPU runtime..."
    Invoke-WebRequest `
        -Uri "https://github.com/ggml-org/llama.cpp/releases/download/b9750/llama-b9750-bin-win-cpu-x64.zip" `
        -OutFile $RuntimeZip
}
if ((Get-FileHash $RuntimeZip -Algorithm SHA256).Hash -ne $RuntimeHash) {
    throw "llama.cpp runtime verification failed."
}
Expand-Archive -LiteralPath $RuntimeZip -DestinationPath $RuntimeDir -Force
$LlamaCli = Get-ChildItem -Path $RuntimeDir -Filter "llama-completion.exe" -File -Recurse | Select-Object -First 1
if (-not $LlamaCli) {
    throw "llama-completion.exe was not found in the llama.cpp archive."
}
if ($LlamaCli.DirectoryName -ne $RuntimeDir) {
    Copy-Item -Path (Join-Path $LlamaCli.DirectoryName "*") -Destination $RuntimeDir -Recurse -Force
}

& $Python -m unittest discover -s (Join-Path $Root "tests") -v
if ($LASTEXITCODE -ne 0) {
    throw "Unit tests failed. Build stopped."
}

$env:ARGOS_PACKAGES_DIR = Join-Path $Root ".build-test\packages"
$env:XDG_DATA_HOME = Join-Path $Root ".build-test\data"
$env:XDG_CONFIG_HOME = Join-Path $Root ".build-test\config"
$env:XDG_CACHE_HOME = Join-Path $Root ".build-test\cache"
& $Python -m scripts.smoke_test_models
if ($LASTEXITCODE -ne 0) {
    throw "Offline translation model validation failed. Build stopped."
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
    throw "PyInstaller build failed. Exit code: $LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $Root "README.txt") -Destination (Join-Path $Root "dist\EETranslator\README.txt") -Force
Copy-Item -LiteralPath (Join-Path $Root "THIRD_PARTY_NOTICES.txt") -Destination (Join-Path $Root "dist\EETranslator\THIRD_PARTY_NOTICES.txt") -Force

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 not found. Run again after install package has been installed."
}
& $Iscc (Join-Path $Root "installer.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup installer build failed."
}

$Installer = Join-Path $Root "installer-output\Wolf-Electrical-Translator-Setup-0.2.1.exe"
$InstallerHash = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "${Installer}.sha256" -Value "$InstallerHash  Wolf-Electrical-Translator-Setup-0.2.1.exe" -Encoding ascii
Write-Host "Installer build completed: $Installer"
Write-Host "SHA-256: $InstallerHash"
