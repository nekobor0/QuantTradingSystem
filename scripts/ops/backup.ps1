param([Parameter(Mandatory=$true)][string]$DatabaseUrl,[Parameter(Mandatory=$true)][string]$OutputFile)
$ErrorActionPreference = "Stop"
pg_dump --format=custom --no-owner --file $OutputFile $DatabaseUrl
Get-FileHash -Algorithm SHA256 -LiteralPath $OutputFile
