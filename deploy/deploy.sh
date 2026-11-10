#!/usr/bin/env bash
# AI Scientist 服务器一键部署脚本（Ubuntu 22.04）
set -e

echo "== 1) 系统依赖 =="
apt-get update -y && apt-get install -y python3-venv python3-pip nginx curl >/dev/null

cd /opt/ai_scientist

echo "== 2) Python 虚拟环境 + 依赖 =="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "== 3) 数据目录 =="
mkdir -p src/users data/runs src/logs
chmod -R 777 src/users data/runs src/logs

echo "== 4) systemd 服务 =="
cp deploy/ai-scientist.service /etc/systemd/system/ai-scientist.service
systemctl daemon-reload
systemctl enable ai-scientist
systemctl restart ai-scientist

echo "== 5) 验证 =="
sleep 3
curl -s http://127.0.0.1:8000/api/runs && echo
echo "部署完成。浏览器访问 http://服务器IP:8000/"
echo "注意：确认 /opt/ai_scientist/.env 已配置（DEEPSEEK_BASE_URL 必须是官方 API）"
