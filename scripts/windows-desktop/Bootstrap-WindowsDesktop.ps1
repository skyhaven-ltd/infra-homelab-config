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
    Where-Object IPAddress -eq $IpAddress

if (-not $currentAddress) {
    Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object PrefixOrigin -eq "Dhcp" |
        Remove-NetIPAddress -Confirm:$false
    Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -Dhcp Disabled
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $IpAddress -PrefixLength $PrefixLength -DefaultGateway $Gateway
}

Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses $DnsServers
Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

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

if (-not (Test-Path -LiteralPath $DeveloperConfigPath)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $DeveloperConfigPath) -Force | Out-Null
    git clone $DeveloperConfigRepository $DeveloperConfigPath
}

& "$DeveloperConfigPath\scripts\Install-DeveloperConfig.ps1" -Repo $DeveloperConfigPath -InstallScheduledTask
