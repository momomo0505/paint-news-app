# Forward today's paint industry news email via Outlook.
# Run from Task Scheduler every Monday at 11:00.

param(
    [string]$MailingList = "",
    [string]$SubjectKeyword = "",
    [string]$IntroTemplate = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $projectRoot ".env"

if (Test-Path $envPath) {
    foreach ($line in Get-Content $envPath -Encoding UTF8) {
        if (-not $MailingList -and $line -match '^\s*MAILING_LIST_EMAIL\s*=\s*(.+)\s*$') {
            $MailingList = $Matches[1].Trim()
        }
        if (-not $SubjectKeyword -and $line -match '^\s*SUBJECT_KEYWORD\s*=\s*(.+)\s*$') {
            $SubjectKeyword = $Matches[1].Trim()
        }
        if (-not $IntroTemplate -and $line -match '^\s*FORWARD_INTRO_TEMPLATE\s*=\s*(.+)\s*$') {
            $IntroTemplate = $Matches[1].Trim()
        }
    }
}

if (-not $SubjectKeyword) {
    Write-Error "SUBJECT_KEYWORD is not set. Add it to .env."
    exit 1
}

if (-not $MailingList) {
    Write-Error "MAILING_LIST_EMAIL is not set. Add it to .env or pass -MailingList."
    exit 1
}

$mailingLists = @(
    $MailingList -split ',' |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ }
)

if ($mailingLists.Count -eq 0) {
    Write-Error "No valid addresses in MAILING_LIST_EMAIL."
    exit 1
}

function Get-ForwardIntro {
    param([string]$Template)

    if (-not $Template) {
        Write-Error "FORWARD_INTRO_TEMPLATE is not set. Add it to .env."
        exit 1
    }

    $now = Get-Date
    return $Template.Replace("{month}", $now.Month).Replace("{day}", $now.Day)
}

$introMessage = Get-ForwardIntro -Template $IntroTemplate

Write-Host "To: $($mailingLists -join ', ')"
Write-Host "Keyword: $SubjectKeyword"
Write-Host "Intro: $introMessage"
Write-Host "Date: $(Get-Date -Format 'yyyy-MM-dd')"

try {
    $outlook = New-Object -ComObject Outlook.Application
    $namespace = $outlook.GetNamespace("MAPI")
    $inbox = $namespace.GetDefaultFolder(6)
} catch {
    Write-Error "Cannot connect to Outlook. Start Outlook and retry. Detail: $_"
    exit 1
}

$today = (Get-Date).Date
$candidates = @()

foreach ($item in $inbox.Items) {
    if ($item.Class -ne 43) { continue }

    $subject = [string]$item.Subject
    if ($subject -notlike "*$SubjectKeyword*") { continue }

    $received = $item.ReceivedTime
    if ($received.Date -ne $today) { continue }

    $candidates += $item
}

if ($candidates.Count -eq 0) {
    Write-Warning "No matching email found for today."
    exit 2
}

$mail = $candidates | Sort-Object { $_.ReceivedTime } -Descending | Select-Object -First 1
Write-Host "Target: [$($mail.ReceivedTime)] $($mail.Subject)"

if ($DryRun) {
    Write-Host "DryRun: skip sending."
    exit 0
}

try {
    $forward = $mail.Forward()
    foreach ($addr in $mailingLists) {
        $null = $forward.Recipients.Add($addr)
    }
    $forward.Subject = $mail.Subject

    if ($forward.HTMLBody) {
        $introHtml = "<p style=""font-size:14px;margin:0 0 16px;"">$introMessage</p>"
        $forward.HTMLBody = $introHtml + $forward.HTMLBody
    } else {
        $forward.Body = "$introMessage`r`n`r`n" + $forward.Body
    }

    $forward.Send()
    Write-Host "Forwarded to: $($mailingLists -join ', ')"
    exit 0
} catch {
    Write-Error "Forward failed: $_"
    exit 1
}
