#!/bin/sh
# =============================================================
# ComptaPro — Deploiement VPS Hostinger KVM2
# Copie ce script sur le VPS et execute-le
# =============================================================
set -e

echo "=== ComptaPro — Deploiement VPS ==="
echo ""

# ── 1. Prérequis ──
command -v docker >/dev/null 2>&1 || {
    echo "Docker non installe. Installation..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable docker --now
    sudo usermod -aG docker "$USER"
    echo "Docker installe. Reconnecte-toi si besoin."
}

command -v docker-compose >/dev/null 2>&1 || {
    echo "Installation docker-compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
}

echo "Docker: $(docker --version)"
echo ""

# ── 2. Création du dossier ──
APP_DIR="/opt/comptapro"
sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER:$USER" "$APP_DIR"
cd "$APP_DIR"

echo "Dossier: $APP_DIR"

# ── 3. Récupération du code (si pas déjà présent) ──
# Option A : Copie manuelle des fichiers via SCP depuis ta machine locale
# Option B : Git clone si tu as un repo
if [ ! -f "Dockerfile" ]; then
    echo ""
    echo "Copie les fichiers suivants depuis ta machine locale vers $APP_DIR/ :"
    echo "  scp -r comptable/ Dockerfile docker-compose.yml docker-compose.prod.yml entrypoint.sh .dockerignore user@vps:$APP_DIR/"
    echo ""
    echo "Puis relance ce script."
    exit 1
fi

echo "Fichiers presents:"
ls -la
echo ""

# ── 4. Build & lancement ──
echo "Construction de l'image Docker..."
docker-compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache

echo "Lancement du conteneur..."
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

echo ""
echo "Attente du demarrage..."
sleep 5

# ── 5. Vérification ──
if curl -sf http://localhost:8080/api/exercices > /dev/null 2>&1; then
    echo "=== DEPLOIEMENT REUSSI ==="
    echo ""
    echo "Acces local:  http://localhost:8080"
    echo "Acces public: http://$(curl -s ifconfig.me):8080"
    echo ""
    echo "Commandes utiles:"
    echo "  docker-compose logs -f    # Voir les logs"
    echo "  docker-compose restart    # Redemarrer"
    echo "  docker-compose down       # Arreter"
    echo "  docker-compose up -d      # Relancer"
    echo ""
    echo "Sauvegarde DB:"
    echo "  docker cp comptapro:/data/comptabilite.db ./backup_\$(date +%Y%m%d).db"
else
    echo "=== ERREUR: Le serveur ne repond pas ==="
    echo "Logs:"
    docker-compose logs --tail=20
    exit 1
fi
