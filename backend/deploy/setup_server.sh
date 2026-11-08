#!/usr/bin/env bash
# One-time setup for the Hawkeye API on a fresh Ubuntu 24.04 EC2 instance.
#
# Run on the server (as the default "ubuntu" user):
#   git clone https://github.com/Lord-Helix07/hawkeye.git ~/hawkeye
#   bash ~/hawkeye/backend/deploy/setup_server.sh
#
# Safe to re-run: it updates code/dependencies and restarts the service.
set -euo pipefail

REPO_DIR="$HOME/hawkeye"
BACKEND_DIR="$REPO_DIR/backend"
DEPLOY_DIR="$BACKEND_DIR/deploy"
DOMAIN="api.fly-hawkeye.com"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip nginx certbot python3-certbot-nginx git \
    libgl1 libglib2.0-0   # libgl1/libglib: needed by OpenCV

echo "==> Adding 2 GB swap (helps YOLO/PyTorch on small instances)"
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "==> Setting up Python virtualenv"
cd "$BACKEND_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
# CPU-only PyTorch first: the default install pulls ~3 GB of GPU (CUDA) libraries
# this server can't use.
./venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
./venv/bin/pip install -r requirements.txt

echo "==> Environment file"
sudo mkdir -p /etc/hawkeye
if [ ! -f /etc/hawkeye/hawkeye.env ]; then
    sudo cp "$DEPLOY_DIR/hawkeye.env.example" /etc/hawkeye/hawkeye.env
    echo "    Created /etc/hawkeye/hawkeye.env -- check AWS_REGION in it."
fi
sudo chmod 640 /etc/hawkeye/hawkeye.env
sudo chown root:ubuntu /etc/hawkeye/hawkeye.env

echo "==> Installing systemd service"
sudo cp "$DEPLOY_DIR/hawkeye-api.service" /etc/systemd/system/hawkeye-api.service
sudo systemctl daemon-reload
sudo systemctl enable hawkeye-api
sudo systemctl restart hawkeye-api

echo "==> Configuring nginx"
# Don't overwrite the file once certbot has added HTTPS to it.
if [ ! -f "/etc/nginx/sites-available/$DOMAIN" ]; then
    sudo cp "$DEPLOY_DIR/nginx-api.fly-hawkeye.com.conf" "/etc/nginx/sites-available/$DOMAIN"
fi
sudo ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "==> Checking the API answers locally"
sleep 5
if curl -fsS http://127.0.0.1:8000/docs > /dev/null; then
    echo "    API is up."
else
    echo "    API not answering yet. Check logs: sudo journalctl -u hawkeye-api -n 50"
fi

cat <<EOF

Done. Next:
  1. Make sure api.fly-hawkeye.com points at this server's Elastic IP (Route 53 A record).
  2. Turn on HTTPS:
       sudo certbot --nginx -d $DOMAIN
  3. Test:  https://$DOMAIN/docs

To deploy new code later:
  cd ~/hawkeye && git pull && bash backend/deploy/setup_server.sh
EOF
