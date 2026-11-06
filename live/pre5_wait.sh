#!/bin/bash
# 周回タイムが出るまで直前情報を取り直す（最大 TRIES 回、60秒おき）。
# usage: bash live/pre5_wait.sh <場> <R> <YYYYMMDD> <出力> [TRIES=5]
P=$1; R=$2; D=$3; OUT=$4; TRIES=${5:-5}
for i in $(seq 1 "$TRIES"); do
  timeout 60 node "$(dirname "$0")/pre5.js" "$P" "$R" "$D" "$OUT" >/dev/null 2>&1
  if grep -P '^周回\t[0-9]' "$OUT" >/dev/null 2>&1; then echo "周回あり（${i}回目）"; exit 0; fi
  echo "周回まだ（${i}回目）"; [ "$i" -lt "$TRIES" ] && sleep 60
done
echo "周回なし（${TRIES}回試した）"; exit 1
