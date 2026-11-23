# Canonical AMI helper for scheduled task StartPodmanMachine.
# Install as C:\scripts\start-podman.ps1 (task must use -NoProfile and this PATH restore).
$ErrorActionPreference = "Stop"

# EC2 may attach a larger root EBS than the AMI partition (e.g. 100GiB volume,
# 40GiB NTFS). Grow C: before Podman creates a VHDx on that drive.
$supported = Get-PartitionSupportedSize -DriveLetter C
$partition = Get-Partition -DriveLetter C
if ($partition.Size -lt $supported.SizeMax) {
    Write-Host ("Extending C: from {0:N0} to {1:N0} bytes..." -f $partition.Size, $supported.SizeMax)
    Resize-Partition -DriveLetter C -Size $supported.SizeMax
}

$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = @(
    "C:\Program Files\RedHat\Podman",
    "C:\Program Files\Podman",
    $machinePath,
    $userPath
) -join ";"

# Nested Hyper-V disk is independent of Windows root size; keep it modest.
$PodmanDiskGiB = 40

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
    Write-Host "No podman-machine-default; initializing with Hyper-V (disk ${PodmanDiskGiB}GiB)..."
    Invoke-Podman -PodmanArgs @(
        "machine", "init", "--provider", "hyperv", "--disk-size", "$PodmanDiskGiB"
    )
}

Invoke-Podman -PodmanArgs @("machine", "start")
Write-Host "Podman machine start issued successfully."
exit 0
