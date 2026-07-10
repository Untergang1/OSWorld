# Run this script from an elevated PowerShell session in the Windows VM.
# It retains manual Windows Update and Defender real-time protection.

$ErrorActionPreference = "Stop"

function Set-DwordPolicy {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [int]$Value
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -Path $Path -Force | Out-Null
    }

    Set-ItemProperty -Path $Path -Name $Name -Type DWord -Value $Value -Force
}

# Disable current-user toast notifications and the notification center.
Set-DwordPolicy `
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\PushNotifications" `
    "ToastEnabled" 0
Set-DwordPolicy `
    "HKCU:\Software\Policies\Microsoft\Windows\CurrentVersion\PushNotifications" `
    "NoToastApplicationNotification" 1
Set-DwordPolicy `
    "HKCU:\Software\Policies\Microsoft\Windows\CurrentVersion\PushNotifications" `
    "NoToastApplicationNotificationOnLockScreen" 1
Set-DwordPolicy `
    "HKCU:\Software\Policies\Microsoft\Windows\Explorer" `
    "DisableNotificationCenter" 1

# Turn off automatic Windows Update behavior without disabling manual updates.
$windowsUpdatePolicy = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
Set-DwordPolicy $windowsUpdatePolicy "NoAutoUpdate" 1
Set-DwordPolicy $windowsUpdatePolicy "NoAutoRebootWithLoggedOnUsers" 1
Set-DwordPolicy $windowsUpdatePolicy "SetAutoRestartNotificationDisable" 1
Set-Service -Name wuauserv -StartupType Manual

# Suppress Windows Security notifications without disabling Defender protection.
$defenderNotificationPolicy = `
    "HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender Security Center\Notifications"
Set-DwordPolicy $defenderNotificationPolicy "DisableNotifications" 1
Set-DwordPolicy $defenderNotificationPolicy "DisableEnhancedNotifications" 1

gpupdate.exe /force

Write-Host ""
Write-Host "Policies applied successfully. Sign out and sign back in before creating the snapshot."
