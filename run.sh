#!/usr/bin/env bash
# 동네가게 예약 시스템 실행 스크립트
# 사용법: bash run.sh   →   http://localhost:5001 (충돌 시 자동 전환)
set -euo pipefail

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  echo "Flask를 설치합니다..."
  pip3 install --quiet --break-system-packages flask
fi

PORT=5001
while (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; do
  PORT=$((PORT + 1))
  if [ "$PORT" -gt 5100 ]; then
    echo "사용 가능한 포트를 찾지 못했습니다 (5001~5100 전부 사용 중)."
    exit 1
  fi
done

echo "=============================================="
echo "  동네가게 예약 시스템"
echo "  손님용: http://localhost:${PORT}"
echo "  사장님용: http://localhost:${PORT}/admin"
echo "  (종료: Ctrl+C)"
echo "=============================================="
PORT="$PORT" exec python3 app.py
