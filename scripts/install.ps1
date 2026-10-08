# rime-en-gloss installer (Windows / Weasel)
#
# English console output on purpose: cmd/PowerShell code pages mangle non-ASCII
# text, and this script is also invoked from .bat wrappers.
#
# Usage (from the repository root):
#     powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# Optional switches:
#     -RimeDir  "D:\Rime"     Rime user directory (default %APPDATA%\Rime)
#     -Schema   wubi_pinyin   schema to patch (default wubi_pinyin)
#     -Python   C://Python313//python.exe/n#     -SkipDeploy             do not redeploy Rime at the end

[CmdletBinding()]
param(
    [string]$RimeDir = "",
    [string]$Schema = "wubi_pinyin",
    [string]$Python = "",
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

if (-not $RimeDir -or $RimeDir -eq "") {
    $RimeDir = Join-Path $env:APPDATA "Rime"
}

Write-Host "== rime-en-gloss installer =="
Write-Host "repo      : $Repo"
Write-Host "rime dir  : $RimeDir"

if (-not (Test-Path $RimeDir)) {
    Write-Host "ERROR: Rime user directory not found. Pass -RimeDir explicitly."
    exit 1
}

# ---------------------------------------------------------------- 1. lua plugin
$LuaDir = Join-Path $RimeDir "lua"
if (-not (Test-Path $LuaDir)) { New-Item -ItemType Directory -Path $LuaDir | Out-Null }
Copy-Item (Join-Path $Repo "lua\input_text.lua") (Join-Path $LuaDir "input_text.lua") -Force
Write-Host "[1/5] lua plugin       -> $LuaDir\input_text.lua"

# ---------------------------------------------------------------- 2. toolchain
$ToolsDir = Join-Path $RimeDir "tools"
if (-not (Test-Path $ToolsDir)) { New-Item -ItemType Directory -Path $ToolsDir | Out-Null }
Copy-Item (Join-Path $Repo "tools\*.py") $ToolsDir -Force
Copy-Item (Join-Path $Repo "data\overrides_legacy.json") $ToolsDir -Force
$DataDir = Join-Path $ToolsDir "data"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }
Write-Host "[2/5] toolchain        -> $ToolsDir"

# ---------------------------------------------------------------- 3. locate python
$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
)
if (-not $Python -or $Python -eq "") {
    foreach ($c in $candidates) {
        if (Test-Path $c) { $Python = $c; break }
    }
}
if (-not $Python -or $Python -eq "") { $Python = "python" }
Write-Host "[3/5] python           -> $Python"
& $Python --version

# ---------------------------------------------------------------- 4. dictionary + cache
$Cedict = Join-Path $DataDir "cedict.json"
if (-not (Test-Path $Cedict)) {
    Write-Host "[4/5] downloading CC-CEDICT ..."
    & $Python (Join-Path $ToolsDir "fetch_cedict.py") --out $Cedict
} else {
    Write-Host "[4/5] CC-CEDICT already present"
}
Write-Host "      building the translation table ..."
& $Python (Join-Path $ToolsDir "build_cache.py") --cedict $Cedict --dict-dir $RimeDir

# ---------------------------------------------------------------- 5. schema patch
$Patch = Join-Path $RimeDir ("{0}.custom.yaml" -f $Schema)
$Wanted = 'lua_filter@*input_text*filter'
$SchemaFile = Join-Path $RimeDir ("{0}.schema.yaml" -f $Schema)
$Already = $false

if (Test-Path $SchemaFile) {
    $txt = Get-Content $SchemaFile -Raw -Encoding UTF8
    if ($txt -match [regex]::Escape($Wanted)) { $Already = $true }
}
if (Test-Path $Patch) {
    $txt = Get-Content $Patch -Raw -Encoding UTF8
    if ($txt -match [regex]::Escape($Wanted)) { $Already = $true }
}

if ($Already) {
    Write-Host "[5/5] filter already registered in $Schema"
} else {
    $block = "patch:`r`n  `"engine/filters/+`":`r`n    - $Wanted`r`n"
    if (Test-Path $Patch) {
        # The file already carries its own patch section; a second "patch:" key
        # would be invalid YAML, so print what to add instead.
        Write-Host "[5/5] ACTION NEEDED: add the following inside the existing patch section of"
        Write-Host "      $Patch"
        Write-Host "      engine/filters/+ :"
        Write-Host "        - $Wanted"
    } else {
        Set-Content -Path $Patch -Value $block -Encoding UTF8
        Write-Host "[5/5] created $Patch"
    }
}

# ---------------------------------------------------------------- deploy
if (-not $SkipDeploy) {
    $Deployer = Join-Path ${env:ProgramFiles} "Rime\weasel-0.17.4\WeaselDeployer.exe"
    if (Test-Path $Deployer) {
        Write-Host "      redeploying Rime ..."
        & $Deployer /deploy
    } else {
        Write-Host "      WeaselDeployer.exe not found - redeploy manually from the tray menu"
    }
}

Write-Host ""
Write-Host "Done."
Write-Host "  * switch to the schema and type: the English appears right of each candidate"
Write-Host "  * table : %TEMP%\rime_argos\cache.txt"
Write-Host "  * patch : $Patch"
Write-Host "  * logs  : set RIME_EN_GLOSS_DEBUG=1 to write %TEMP%\rime_argos\filter_debug.log"
