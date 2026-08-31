# Forward today's paint industry news email via Outlook.
# Run from Task Scheduler every Monday at 11:00.

param(
    [string]$MailingList = "",
    [string]$SubjectKeyword = "",
    [string]$IntroTemplate = "",
    [int]$MaxWaitMinutes = 90,
    [int]$RetryIntervalMinutes = 10,
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

$today = (Get-Date).Date
$todayKey = $today.ToString("yyyy-MM-dd")
$stateFile = Join-Path $projectRoot ".forward-state"

# 手動転送とリトライ中の自動実行が重なった場合の二重送信を防ぐ
if (-not $DryRun -and (Test-Path $stateFile)) {
    if ((Get-Content $stateFile -Raw).Trim() -eq $todayKey) {
        Write-Host "Already forwarded today ($todayKey). Skip."
        exit 0
    }
}

try {
    $outlook = New-Object -ComObject Outlook.Application
    $namespace = $outlook.GetNamespace("MAPI")
    $inbox = $namespace.GetDefaultFolder(6)
} catch {
    Write-Error "Cannot connect to Outlook. Start Outlook and retry. Detail: $_"
    exit 1
}

function Find-TodayNewsMail {
    param($Inbox, [string]$Keyword, [datetime]$Today)

    $found = @()
    foreach ($item in $Inbox.Items) {
        if ($item.Class -ne 43) { continue }

        $subject = [string]$item.Subject
        if ($subject -notlike "*$Keyword*") { continue }

        if ($item.ReceivedTime.Date -ne $Today) { continue }

        $found += $item
    }
    return $found
}

# 配信元 (GitHub Actions) の起動遅延や Outlook への取り込み遅れで
# 実行時点ではまだ届いていないことがあるため、一定時間ポーリングする
$deadline = (Get-Date).AddMinutes($MaxWaitMinutes)
$candidates = @()

while ($true) {
    $candidates = @(Find-TodayNewsMail -Inbox $inbox -Keyword $SubjectKeyword -Today $today)
    if ($candidates.Count -gt 0) { break }

    if ($DryRun -or (Get-Date) -ge $deadline) { break }

    Write-Host "Not found yet. Retrying in $RetryIntervalMinutes min (deadline: $($deadline.ToString('HH:mm')))."
    try { $namespace.SendAndReceive($false) } catch { }
    Start-Sleep -Seconds ($RetryIntervalMinutes * 60)
}

if ($candidates.Count -eq 0) {
    Write-Warning "No matching email found for today (waited up to $MaxWaitMinutes min)."
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
    Set-Content -Path $stateFile -Value $todayKey -Encoding UTF8
    exit 0
} catch {
    Write-Error "Forward failed: $_"
    exit 1
}
