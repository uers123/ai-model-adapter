param(
  [Parameter(Mandatory=$true)][ValidateSet('start','status','watch','unwatch','pause','resume','stop')][string]$Action,
  [Parameter(Mandatory=$true)][string]$CampaignId,
  [string]$TasksRoot = $env:AI_MODEL_ADAPTER_TASKS
)

if ([string]::IsNullOrWhiteSpace($TasksRoot)) { $TasksRoot = 'D:\github-neirong\AI模型特调任务' }
$cli = Join-Path $PSScriptRoot 'cli.py'
$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @($cli, $Action, $CampaignId, '--tasks', $TasksRoot)

if ($Action -eq 'start') {
  Start-Process -FilePath $python -ArgumentList $arguments -WindowStyle Hidden
} else {
  & $python @arguments
}
