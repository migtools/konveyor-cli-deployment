# Canonical AMI helper for scheduled task StartPodmanMachine.
# Install as C:\scripts\start-podman.ps1 (task must use -NoProfile and this PATH restore).
$ErrorActionPreference = "Stop"

$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = @(
    "C:\Program Files\RedHat\Podman",
    "C:\Program Files\Podman",
    $machinePath,
    $userPath
) -join ";"

function Invoke-Podman {
    param([Parameter(Mandatory = $true)][string[]]$PodmanArgs)
    & podman @PodmanArgs
    if ($LASTEXITCODE -ne 0) {
        throw "podman $($PodmanArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

$inspect = & podman machine inspect podman-machine-default 2>&1
$inspectText = ($inspect | Out-String)
if (
    $LASTEXITCODE -ne 0 -or
    $inspectText -match "no such machine" -or
    $inspectText -match "VM does not exist"
) {
    Write-Host "No podman-machine-default; initializing with Hyper-V..."
    Invoke-Podman -PodmanArgs @("machine", "init", "--provider", "hyperv")
}

Invoke-Podman -PodmanArgs @("machine", "start")
Write-Host "Podman machine start issued successfully."
exit 0
