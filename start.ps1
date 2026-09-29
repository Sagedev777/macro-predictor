New-Item -ItemType File -Path "config\__init__.py" -Force | Out-Null

Write-Host "Starting MacroPredictor API..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; .\venv\Scripts\activate; python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload" -WindowStyle Normal

Write-Host "Starting Dashboard..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; npm run dev" -WindowStyle Normal

Write-Host ""
Write-Host "✅ MacroPredictor is starting!" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:  http://localhost:5173" -ForegroundColor Yellow
Write-Host "  API:        http://localhost:8000" -ForegroundColor Yellow
Write-Host ""
Write-Host "Wait 10 seconds then open http://localhost:5173 in your browser." -ForegroundColor White
Start-Sleep -Seconds 2
