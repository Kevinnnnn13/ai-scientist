# AI Scientist build script v5 - onedir + slim + DLL repair (2026-08-26)
# Usage: run in project root:
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
# Output: dist\AI_Scientist\ (exe + _internal), auto-zipped to dist\AI_Scientist.zip

# NOTE: use Continue (not Stop). Under Stop, Windows PowerShell 5.1 turns
# native-command stderr (e.g. python traceback) into a fatal error and aborts.
$ErrorActionPreference = "Continue"
$py = "C:\Users\22011\anaconda3\python.exe"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== 1) Check deps (PyInstaller / pypdf) =="
& $py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "  Installing PyInstaller ..."
  & $py -m pip install pyinstaller
  if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }
}
& $py -c "import pypdf" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "  Installing pypdf (PDF parsing) ..."
  & $py -m pip install pypdf
  if ($LASTEXITCODE -ne 0) { throw "pip install pypdf failed" }
}

Write-Host "== 2) Build (onedir, about 4-10 min) =="
$pyargs = @(
  "--noconfirm", "--clean", "--onedir",
  "--name", "AI_Scientist",
  "--add-data", "web\index.html;web",
  "--add-data", "src\s125_all.txt;src",
  "--hidden-import", "tavily",
  "--hidden-import", "dotenv",
  "--hidden-import", "openai",
  "--hidden-import", "matplotlib.backends.backend_agg",
  "--hidden-import", "pypdf",
  "--exclude-module", "PyQt5",
  "--exclude-module", "PyQt6",
  "--exclude-module", "PySide6",
  "--exclude-module", "PySide2",
  "--exclude-module", "torch",
  "--exclude-module", "torchvision",
  "--exclude-module", "torchaudio",
  "--exclude-module", "nltk",
  "--exclude-module", "IPython",
  "--exclude-module", "jupyter",
  "--exclude-module", "notebook",
  "--exclude-module", "sphinx",
  "--exclude-module", "jedi",
  "--exclude-module", "black",
  "--exclude-module", "zmq",
  "--exclude-module", "vtk",
  "--exclude-module", "vtkmodules",
  "--exclude-module", "panel",
  "--exclude-module", "bokeh",
  "--exclude-module", "botocore",
  "--exclude-module", "boto3",
  "--exclude-module", "bitsandbytes",
  "--exclude-module", "spacy",
  "--exclude-module", "transformers",
  "--exclude-module", "llvmlite",
  "--exclude-module", "numba",
  "--exclude-module", "scipy",
  "--exclude-module", "pandas",
  "--exclude-module", "sklearn",
  "--exclude-module", "statsmodels",
  "--exclude-module", "plotly",
  "--exclude-module", "skimage",
  "--exclude-module", "pyarrow",
  "--exclude-module", "astropy",
  "src\launcher.py"
)
& $py -m PyInstaller @pyargs 2>&1 | Tee-Object -FilePath "build_attempt.log"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed, see build_attempt.log" }

Write-Host "== 3) Slim: remove wrongly-bundled big libs =="
$internal = Join-Path $root "dist\AI_Scientist\_internal"
$deadDirs = @("torch","vtk.libs","vtkmodules","bitsandbytes","panel","botocore","boto3","llvmlite","spacy","transformers","scipy","pandas","sklearn","statsmodels","plotly","skimage","pyarrow","blis","thinc","hf_xet","tokenizers","astropy","astropy_iers_data","bokeh","numba")
foreach ($d in $deadDirs) {
  $p = Join-Path $internal $d
  if (Test-Path $p) {
    Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
    Write-Host "  removed: $d"
  }
}
$deadDlls = @("cublasLt64_12.dll","cublas64_12.dll","cudart64_12.dll")
foreach ($f in $deadDlls) {
  Get-ChildItem -Path $internal -Recurse -File -Filter $f -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item -Force $_.FullName -ErrorAction SilentlyContinue
    Write-Host "  removed: $($_.Name)"
  }
}

Write-Host "== 3.5) Repair missing runtime DLLs (PIL/lxml/yaml/cares) =="
$libbin = "C:\Users\22011\anaconda3\Library\bin"
$repairDlls = @("avif.dll","cares.dll","charset.dll","deflate.dll","freetype.dll","iconv.dll","lcms2.dll","Lerc.dll","libexslt.dll","libjpeg.dll","liblzma.dll","libpng16.dll","libsharpyuv.dll","libwebp.dll","libwebpdemux.dll","libwebpmux.dll","libxml2.dll","libxslt.dll","openjp2.dll","tiff.dll","yaml.dll","zstd.dll")
foreach ($n in $repairDlls) {
  $dst = Join-Path $internal $n
  if (-not (Test-Path $dst)) {
    $src = Join-Path $libbin $n
    if (Test-Path $src) {
      Copy-Item -LiteralPath $src -Destination $dst -Force
      Write-Host "  copied: $n"
    } else {
      Write-Host "  WARN: source not found in Library\bin: $n"
    }
  }
}
$missingRepair = @($repairDlls | Where-Object { -not (Test-Path (Join-Path $internal $_)) })
if ($missingRepair.Count -gt 0) {
  throw ("Repair failed, still missing: " + ($missingRepair -join ", "))
}
Write-Host ("  repair OK: all " + $repairDlls.Count + " DLLs present")

Write-Host "== 4) Re-zip =="
$zipPath = Join-Path $root "dist\AI_Scientist.zip"
if (Test-Path $zipPath) {
  try { Remove-Item -Force $zipPath } catch { Write-Host "  WARN: old zip is locked, skip delete" }
}
Compress-Archive -Path (Join-Path $root "dist\AI_Scientist") -DestinationPath $zipPath -CompressionLevel Optimal
$dirMB = [math]::Round(((Get-ChildItem (Join-Path $root "dist\AI_Scientist") -Recurse -File | Measure-Object Length -Sum).Sum)/1MB,1)
$zipMB = [math]::Round((Get-Item $zipPath).Length/1MB,1)
Write-Host ""
Write-Host "=============================================="
Write-Host "DONE!"
Write-Host "  folder size: $dirMB MB"
Write-Host "  zip size:    $zipMB MB"
Write-Host "  distribute: dist\AI_Scientist.zip (unzip, double-click AI_Scientist.exe)"
Write-Host "=============================================="
