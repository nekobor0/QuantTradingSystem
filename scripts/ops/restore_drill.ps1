param(
  [Parameter(Mandatory=$true)][string]$IsolatedDatabaseUrl,
  [Parameter(Mandatory=$true)][string]$BackupFile,
  [Parameter(Mandatory=$true)][string]$ExpectedChecksum,
  [Parameter(Mandatory=$true)][string]$ExpectedSchemaVersion,
  [Parameter(Mandatory=$true)][int]$ExpectedCriticalRowCount
)
$ErrorActionPreference = "Stop"
if ($IsolatedDatabaseUrl -match "(?i)(prod|production)") { throw "Refusing restore drill against a production-like target" }
$actualChecksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $BackupFile).Hash
if ($actualChecksum -ne $ExpectedChecksum) { throw "Backup checksum mismatch" }
pg_restore --exit-on-error --clean --if-exists --no-owner --dbname $IsolatedDatabaseUrl $BackupFile
$schemaVersion = psql $IsolatedDatabaseUrl -v ON_ERROR_STOP=1 -tA -c "SELECT schema_version FROM ops_backup_records ORDER BY finished_at DESC LIMIT 1;"
if ($schemaVersion.Trim() -ne $ExpectedSchemaVersion) { throw "Restored schema version mismatch" }
$criticalRows = psql $IsolatedDatabaseUrl -v ON_ERROR_STOP=1 -tA -c "SELECT (SELECT COUNT(*) FROM ops_task_runs) + (SELECT COUNT(*) FROM ops_outbox_events) + (SELECT COUNT(*) FROM ops_audit_logs);"
if ([int]$criticalRows -ne $ExpectedCriticalRowCount) { throw "Restored critical row count mismatch" }
