<#
.SYNOPSIS
  One-time PostgreSQL provisioning for Urban Sentinel: creates an application role and database.

.DESCRIPTION
  Needs the PostgreSQL superuser password in $env:PGPASSWORD (never passed on the command line).
  Creates the role and database only if they do not exist, and grants CREATE on the public schema
  (required on PostgreSQL 15+). Never prints any password.

.EXAMPLE
  $env:PGPASSWORD = "<postgres-superuser-password>"
  .\scripts\provision_db.ps1 -Database urban_sentinel -User urban_sentinel -Password "<app-password>"
#>
param(
    [string]$Database = "urban_sentinel",
    [string]$User = "urban_sentinel",
    [Parameter(Mandatory = $true)][string]$Password,
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$Superuser = "postgres"
)

$ErrorActionPreference = "Stop"

if (-not $env:PGPASSWORD) {
    Write-Error "Set `$env:PGPASSWORD to the PostgreSQL superuser password first."
}
if ($Database -notmatch '^[a-z_][a-z0-9_]*$' -or $User -notmatch '^[a-z_][a-z0-9_]*$') {
    Write-Error "Database and user names must match ^[a-z_][a-z0-9_]*$."
}

$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) {
    $candidate = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $candidate) { Write-Error "psql not found. Add PostgreSQL's bin directory to PATH." }
    $psqlPath = $candidate.FullName
} else {
    $psqlPath = $psql.Source
}

$escapedPassword = $Password.Replace("'", "''")
$common = @("-h", $PgHost, "-p", "$Port", "-U", $Superuser, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A")

$roleExists = & $psqlPath @common -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname = '$User'"
if ($roleExists -ne "1") {
    "CREATE ROLE $User LOGIN PASSWORD '$escapedPassword';" | & $psqlPath @common -d postgres | Out-Null
    Write-Host "Created role $User"
} else {
    Write-Host "Role $User already exists (password unchanged)"
}

$dbExists = & $psqlPath @common -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$Database'"
if ($dbExists -ne "1") {
    & $psqlPath @common -d postgres -c "CREATE DATABASE $Database OWNER $User" | Out-Null
    Write-Host "Created database $Database"
} else {
    Write-Host "Database $Database already exists"
}

& $psqlPath @common -d $Database -c "GRANT CREATE ON SCHEMA public TO $User" | Out-Null
Write-Host "Done. Next: set DATABASE_URL and run '.\.venv\Scripts\alembic.exe upgrade head'."
