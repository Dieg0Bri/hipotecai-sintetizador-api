# ============================================================================
# sintetizador-api - cuenta de servicio dedicada
# ============================================================================
# Permisos:
#   - cloudsql.client                  lee dt_extraccion, persiste dt_sintetizador
#   - secretmanager.secretAccessor     db-password
# ============================================================================

. "$PSScriptRoot\..\infra\config.ps1"

$SA_NAME  = "sintetizador-api-sa"
$SA_EMAIL = "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "  Cuenta : $SA_EMAIL"

$exists = gcloud iam service-accounts describe $SA_EMAIL --project=$PROJECT_ID --format="value(email)" 2>$null
if ($exists -eq $SA_EMAIL) {
  Write-Host "  [--] SA ya existe" -ForegroundColor Gray
} else {
  gcloud iam service-accounts create $SA_NAME `
    --display-name="sintetizador-api" `
    --description="Une extracciones del estudio en grafo NetworkX" `
    --project=$PROJECT_ID --quiet
  Write-Host "  [OK] SA creada" -ForegroundColor Green
}

Write-Host "  Roles:"
$roles = @("roles/cloudsql.client", "roles/secretmanager.secretAccessor")
foreach ($role in $roles) {
  gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SA_EMAIL" `
    --role="$role" --condition=None --quiet 2>&1 | Out-Null
  Write-Host "    - $role"
}
