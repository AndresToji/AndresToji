#!/bin/bash
# Script para configurar GitHub Pages y el workflow
# Ejecuta este script desde la raíz de tu repositorio

echo "Configurando GitHub Pages y Workflow..."

# Crear la estructura de carpetas
mkdir -p .github/workflows

# Crear el archivo del workflow
cat > .github/workflows/scan.yml << 'EOF'
name: Bot de Señales Binance

on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch: {}

jobs:
  escanear:
    runs-on: ubuntu-latest
    steps:
      - name: Clonar repositorio
        uses: actions/checkout@v4

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Instalar dependencias
        run: pip install -r requirements.txt

      - name: Ejecutar bot
        run: python binance_signal_bot.py --pares 30 --velas 4h

      - name: Hacer commit de cambios
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add señales_binance.json señales_binance.csv || true
          git commit -m "🤖 Actualizar señales $(date -u +'%Y-%m-%d %H:%M:%S UTC')" || true
          git push || true
EOF

echo "✅ Workflow creado en .github/workflows/scan.yml"
echo "Ahora debes hacer push de estos cambios a GitHub:"
echo ""
echo "git add .github/workflows/scan.yml"
echo "git commit -m 'Add GitHub Actions workflow for signal bot'"
echo "git push"
echo ""
echo "El dashboard estará disponible en: https://andrestoji.github.io/AndresToji/"
