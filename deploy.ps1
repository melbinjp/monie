<#
.SYNOPSIS
    Deploys Project Monie to EC2

.DESCRIPTION
    This script automates the deployment process:
    1. Stages all local changes
    2. Prompts for a commit message
    3. Commits and pushes to GitHub
    4. Connects to EC2, pulls latest code, and restarts the service
#>

param (
    [string]$CommitMessage
)

if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
    $CommitMessage = Read-Host -Prompt "Enter commit message (or press enter for 'Auto-deploy update')"
    if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
        $CommitMessage = "Auto-deploy update"
    }
}

Write-Host "`n[1/5] Running Local CI Checks (Syntax Validation)..." -ForegroundColor Cyan
$pythonFiles = Get-ChildItem -Path . -Filter *.py -Recurse | Where-Object { $_.FullName -notmatch "\\.venv" }
$compileFailed = $false
foreach ($file in $pythonFiles) {
    python -m py_compile $file.FullName
    if ($LASTEXITCODE -ne 0) {
        $compileFailed = $true
        Write-Host "Compile error in: $($file.Name)" -ForegroundColor Red
    }
}

if ($compileFailed) {
    Write-Host "❌ CI Pipeline Failed: Syntax or Compilation Error detected." -ForegroundColor Red
    Write-Host "Deployment aborted. Please fix the code and try again." -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/5] Staging changes..." -ForegroundColor Cyan
git add -A

# Check if there are changes to commit
$status = git status --porcelain
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "No local changes to commit. Proceeding to sync EC2 anyway..." -ForegroundColor Yellow
} else {
    Write-Host "[3/5] Committing code to local branch..." -ForegroundColor Cyan
    git commit -m $CommitMessage
    
    Write-Host "[4/5] Pushing code to GitHub (origin/main)..." -ForegroundColor Cyan
    git push origin main
}

Write-Host "`n[5/5] Connecting to EC2 to pull and restart Monie Bot..." -ForegroundColor Cyan
$sshKey = "monie-key.pem"
$ec2User = "ubuntu"
$ec2Host = "13.205.207.244"
$remoteCmd = "cd ~/monie && git pull origin main && sudo systemctl daemon-reload && sudo systemctl restart monie && sleep 2 && sudo systemctl status monie --no-pager"

ssh -o StrictHostKeyChecking=no -i $sshKey "$ec2User@$ec2Host" $remoteCmd

Write-Host "`n✅ Deployment Complete! The bot has been updated and restarted on EC2." -ForegroundColor Green
