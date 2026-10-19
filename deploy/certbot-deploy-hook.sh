#!/bin/sh
# certbot 续期后让 Caddy 重新加载证书。安装：
#   cp deploy/certbot-deploy-hook.sh /etc/letsencrypt/renewal-hooks/deploy/puhui-caddy.sh && chmod +x 同上
# 将 COMPOSE_DIR 改为 docker-compose.yml 所在目录
COMPOSE_DIR=/opt/puhui-workbench
cd "$COMPOSE_DIR" && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --force
