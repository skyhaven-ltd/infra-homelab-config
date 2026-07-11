[CmdletBinding()]
param (
    [string]$InterfaceAlias = "Ethernet",
    [string]$IpAddress = "192.168.1.4",
    [int]$PrefixLength = 24,
    [string]$Gateway = "192.168.1.1",
    [string[]]$DnsServers = @("1.1.1.1", "8.8.8.8"),
    [string]$DeveloperConfigRepository = "https://github.com/skyhaven-ltd/infra-developer-config.git",
    [string]$DeveloperConfigPath = "$env:USERPROFILE\source\infra-developer-config"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session"
}

$adapter = Get-NetAdapter -Name $InterfaceAlias
$currentAddress = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq $IpAddress -and $_.PrefixLength -eq $PrefixLength }
$currentGateway = Get-NetRoute -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Where-Object NextHop -eq $Gateway
$ipInterface = Get-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4

if (-not $currentAddress -or -not $currentGateway -or $ipInterface.Dhcp -ne "Disabled") {
    Get-NetRoute -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Remove-NetRoute -Confirm:$false
    Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "169.254.*" } |
        Remove-NetIPAddress -Confirm:$false
    Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -Dhcp Disabled
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $IpAddress -PrefixLength $PrefixLength -DefaultGateway $Gateway
}

Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses $DnsServers
Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
Get-NetFirewallRule -DisplayGroup "Remote Desktop" |
    Get-NetFirewallAddressFilter |
    Set-NetFirewallAddressFilter -RemoteAddress "100.64.0.0/10"

$packages = @(
    @{ Id = "Git.Git"; Source = "winget" },
    @{ Id = "GitHub.cli"; Source = "winget" },
    @{ Id = "Microsoft.VisualStudioCode"; Source = "winget" },
    @{ Id = "Tailscale.Tailscale"; Source = "winget" },
    @{ Id = "9NT1R1C2HH7J"; Source = "msstore" }
)

foreach ($package in $packages) {
    winget install --id $package.Id --exact --source $package.Source --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -notin @(0, -1978335189)) {
        throw "Failed to install $($package.Id): winget exit code $LASTEXITCODE"
    }
}

$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Test-Path -LiteralPath $DeveloperConfigPath)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $DeveloperConfigPath) -Force | Out-Null
    git clone $DeveloperConfigRepository $DeveloperConfigPath
} else {
    git -C $DeveloperConfigPath pull --ff-only
}

& "$DeveloperConfigPath\scripts\Install-DeveloperConfig.ps1" -Repo $DeveloperConfigPath -InstallScheduledTask
