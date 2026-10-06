#!/usr/bin/env bash
# Tải The Public Jira Dataset (Zenodo 15719919) + công cụ MongoDB (không cần root)
# rồi restore dump vào mongod local @127.0.0.1:27017, db JiraReposAnon.
#
# Dùng:  bash jira_adapter/download_dataset.sh [download|tools|start|restore|stop|all]
#        (mặc định: all = download + tools + start + restore)
# Biến môi trường (tùy chọn): RAW_DIR, TOOLS_DIR, MONGO_PORT, MONGO_VER, TOOLS_VER, MONGO_OS
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW_DIR="${RAW_DIR:-$ROOT/data/raw}"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/.tools}"
MONGO_PORT="${MONGO_PORT:-27017}"
MONGO_VER="${MONGO_VER:-9.0.2}"
TOOLS_VER="${TOOLS_VER:-100.19.1}"
MONGO_OS="${MONGO_OS:-ubuntu2404}"   # vd ubuntu2204, rhel93 — xem mongodb.com/try/download

ZENODO_URL="https://zenodo.org/api/records/15719919/files/2025-06-23%20ThePublicJiraDataset.zip/content"
ZENODO_MD5="02f85309d966092ea130ca0797aea795"
ZIP="$RAW_DIR/ThePublicJiraDataset.zip"
ARCHIVE="$RAW_DIR/ThePublicJiraDataset/3. DataDump/mongodump-JiraReposAnon.archive"

SERVER_NAME="mongodb-linux-x86_64-$MONGO_OS-$MONGO_VER"
TOOLS_NAME="mongodb-database-tools-$MONGO_OS-x86_64-$TOOLS_VER"
MONGOD="$TOOLS_DIR/$SERVER_NAME/bin/mongod"
MONGORESTORE="$TOOLS_DIR/$TOOLS_NAME/bin/mongorestore"
DB_PATH="$TOOLS_DIR/mongo-data"
LOG="$TOOLS_DIR/mongod.log"

log() { echo "[download_dataset] $*"; }

download() {
  mkdir -p "$RAW_DIR"
  if [[ -f "$ARCHIVE" ]]; then log "đã có $ARCHIVE — bỏ qua"; return; fi
  log "tải dataset 5.81GB -> $ZIP (resume được nếu bị ngắt)"
  curl -fL -C - --retry 5 -o "$ZIP" "$ZENODO_URL"
  log "kiểm tra md5"
  echo "$ZENODO_MD5  $ZIP" | md5sum -c -
  log "giải nén"
  unzip -q -o "$ZIP" -d "$RAW_DIR"
  [[ -f "$ARCHIVE" ]] || { log "không thấy $ARCHIVE sau khi giải nén"; exit 1; }
}

tools() {
  mkdir -p "$TOOLS_DIR"
  if [[ ! -x "$MONGOD" ]]; then
    log "tải mongod $MONGO_VER"
    curl -fL --retry 5 "https://fastdl.mongodb.org/linux/$SERVER_NAME.tgz" | tar -xz -C "$TOOLS_DIR"
  fi
  if [[ ! -x "$MONGORESTORE" ]]; then
    log "tải mongodb-database-tools $TOOLS_VER"
    curl -fL --retry 5 "https://fastdl.mongodb.org/tools/db/$TOOLS_NAME.tgz" | tar -xz -C "$TOOLS_DIR"
  fi
  "$MONGOD" --version | head -1
  "$MONGORESTORE" --version | head -1
}

start() {
  mkdir -p "$DB_PATH"
  if pgrep -f "mongod .*--dbpath $DB_PATH" >/dev/null; then
    log "mongod đang chạy"; return
  fi
  log "khởi động mongod @127.0.0.1:$MONGO_PORT (dbpath $DB_PATH)"
  "$MONGOD" --dbpath "$DB_PATH" --bind_ip 127.0.0.1 --port "$MONGO_PORT" --fork --logpath "$LOG"
}

restore() {
  log "restore (~15-30 phút, ~60GB sau khi bung)"
  "$MONGORESTORE" --host "127.0.0.1:$MONGO_PORT" --gzip --archive="$ARCHIVE" \
    --nsFrom "JiraReposAnon.*" --nsTo "JiraReposAnon.*" --numInsertionWorkersPerCollection 4
}

stop() {
  "$MONGOD" --dbpath "$DB_PATH" --shutdown
}

case "${1:-all}" in
  download) download ;;
  tools) tools ;;
  start) start ;;
  restore) restore ;;
  stop) stop ;;
  all) download; tools; start; restore ;;
  *) echo "usage: $0 [download|tools|start|restore|stop|all]"; exit 2 ;;
esac
