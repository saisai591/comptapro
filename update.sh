#!/bin/sh
# ===========================================
# ComptaPro — Script de mise à jour auto
# Exécute ce script depuis le terminal Hostinger
# Usage: ./update.sh
# ===========================================
set -e

APP_DIR="/opt/comptapro"
if [ ! -d "$APP_DIR" ]; then
    echo "Clonage du repo..."
    git clone https://github.com/saisai591/comptapro.git "$APP_DIR"
fi
cd "$APP_DIR"

echo ""
echo "=== ComptaPro — Mise à jour ==="
echo ""

# 1. Pull latest
echo "[1/4] git pull..."
git pull origin main

# 2. Build
echo "[2/4] docker compose build..."
docker compose build --no-cache

# 3. Restart
echo "[3/4] redémarrage..."
docker compose down
docker compose up -d

# 4. Health check
echo "[4/4] vérification..."
sleep 3
if curl -sf http://localhost:8080/api/auth/me > /dev/null 2>&1; then
    echo ""
    echo "✅ Mise à jour réussie !"
    echo "   http://$(curl -s ifconfig.me 2>/dev/null || echo 'TON_IP'):8080"
else
    echo ""
    echo "⚠️  Le serveur ne répond pas. Logs :"
    docker compose logs --tail=15
fi

echo ""
echo "Sauvegarde DB rapide :"
docker cp comptapro:/data/comptabilite.db "./backup_$(date +%Y%m%d_%H%M%S).db" 2>/dev/null && echo "   OK" || echo "   (pas de conteneur comptapro)"
