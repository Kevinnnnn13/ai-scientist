param(
    [string]$Python = "python",
    [string]$Pdftoppm = ""
)

$ErrorActionPreference = "Stop"
$figureBuildScript = Join-Path $PSScriptRoot "build.py"
$figureBuildArguments = @("-B", $figureBuildScript)
if ($Pdftoppm) {
    $figureBuildArguments += @("--pdftoppm", $Pdftoppm)
}
& $Python @figureBuildArguments
if ($LASTEXITCODE -ne 0) {
    throw "Figure generation failed with exit code $LASTEXITCODE."
}
