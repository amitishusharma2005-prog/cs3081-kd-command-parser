# One-click Windows setup + run. Installs WSL2 + Ubuntu + Docker Engine on the drive with the most free space
# (not Docker Desktop, not C:), then runs the whole project. Safe to run again: it continues where it stopped.
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$User = "student"
$TaskName = "CS3081Resume"
function Say($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function ToWsl($p) { $d = $p.Substring(0, 1).ToLower(); return "/mnt/$d" + ($p.Substring(2) -replace '\\', '/') }
function Get-Distros {
    try { $old = [Console]::OutputEncoding; [Console]::OutputEncoding = [System.Text.Encoding]::Unicode
          $o = & wsl.exe -l -q 2>$null; [Console]::OutputEncoding = $old
          return @($o | ForEach-Object { "$_".Trim() } | Where-Object { $_ }) } catch { return @() }
}
function Run-Wsl([string[]]$a) { & wsl.exe @a; if ($LASTEXITCODE -ne 0) { throw "wsl $($a -join ' ') failed (exit $LASTEXITCODE)" } }

Say "Keeping the laptop awake while it works"
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-ac 0 | Out-Null

# ---- pick the drive with the most free space (so C: with little space is not used)
$drive = (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 -and $_.Name.Length -eq 1 } | Sort-Object Free -Descending | Select-Object -First 1)
$D = $drive.Name + ":"
$freeGB = [math]::Round($drive.Free / 1GB)
Say "Installing to drive $D ($freeGB GB free)"
if ($freeGB -lt 35) { Warn "Only $freeGB GB free on the best drive; 35 GB or more is recommended. Continuing anyway." }
$Work = "$D\cs3081-env"; $WslDir = "$D\wsl\Ubuntu"
New-Item -ItemType Directory -Force -Path $Work, $WslDir | Out-Null

# ---- 1. Windows features for WSL2 (may need ONE restart; the script resumes by itself after logon)
Say "1/5 Windows features for WSL2"
$need = $false
foreach ($f in "Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform") {
    if ((Get-WindowsOptionalFeature -Online -FeatureName $f).State -ne "Enabled") {
        Enable-WindowsOptionalFeature -Online -FeatureName $f -NoRestart | Out-Null; $need = $true
    }
}
if ($need) {
    schtasks /Create /TN $TaskName /SC ONLOGON /RL HIGHEST /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" | Out-Null
    Warn "Windows needs ONE restart to finish enabling WSL2. Save your work. Restarting in 30 seconds; after you log in, this setup continues by itself."
    Start-Sleep 30; Restart-Computer -Force; exit 0
}
try { & wsl.exe --update --web-download | Out-Null } catch { }
& wsl.exe --set-default-version 2 | Out-Null

# ---- memory limit for WSL (75% of RAM) and swap on the big drive
$cfg = "$env:USERPROFILE\.wslconfig"
if (-not (Test-Path $cfg)) {
    $ram = [math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    $mem = [math]::Max(6, [math]::Floor($ram * 0.75))
    $swap = ("$D\wsl\swap.vhdx").Replace('\', '\\')
    Set-Content -Path $cfg -Value "[wsl2]`nmemory=${mem}GB`nswap=8GB`nswapFile=$swap`n"
    & wsl.exe --shutdown
}

# ---- 2. Ubuntu, imported straight onto the big drive
Say "2/5 Ubuntu on $D"
if ((Get-Distros) -notcontains "Ubuntu") {
    $tar = "$Work\ubuntu-rootfs.tar.gz"
    if (-not (Test-Path $tar) -or (Get-Item $tar).Length -lt 300MB) {
        Write-Host "Downloading Ubuntu 24.04 (about 340 MB)..."
        & curl.exe -L --fail -o $tar "https://cloud-images.ubuntu.com/wsl/releases/noble/current/ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz"
        if ($LASTEXITCODE -ne 0) { throw "download failed: check your internet connection and run this again." }
    }
    Run-Wsl @("--import", "Ubuntu", $WslDir, $tar, "--version", "2")
    Remove-Item $tar -Force
}
& wsl.exe --set-default Ubuntu | Out-Null

# ---- 3. user, systemd, Docker Engine inside Ubuntu
Say "3/5 Docker Engine inside Ubuntu (no Docker Desktop needed)"
$wslHere = ToWsl $Here
Run-Wsl @("-d", "Ubuntu", "-u", "root", "--", "bash", "$wslHere/scripts/wsl_bootstrap.sh", $User)
& wsl.exe --terminate Ubuntu | Out-Null
Start-Sleep 3
Run-Wsl @("-d", "Ubuntu", "-u", "root", "--", "bash", "$wslHere/scripts/wsl_wait_docker.sh")

# ---- 4. the project
Say "4/5 Running the whole project (the long part: hours; do not close this window; closing it is safe, run the .bat again)"
& wsl.exe -d Ubuntu -u $User -- bash "$wslHere/scripts/wsl_launch.sh" "$wslHere"
$rc = $LASTEXITCODE

Say "5/5 Bringing the result back"
& wsl.exe -d Ubuntu -u $User -- bash "$wslHere/scripts/wsl_copy_back.sh" "$wslHere"
if (Test-Path "$Here\230103033.zip") {
    schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
    Write-Host "DONE: $Here\230103033.zip" -ForegroundColor Green
    Write-Host "Your project in Ubuntu (for the handwritten scan): \\wsl.localhost\Ubuntu\home\$User\cs3081-kd-command-parser" -ForegroundColor Green
} elseif ($rc -ne 0) {
    Warn "The run stopped. Read the last lines above or results\pipeline_run.log, fix the cause (or send it to me), and double-click RUN_EVERYTHING.bat again: finished stages are skipped."
}
