set -e

chown -R etluser:etlgroup /app/logs 2>/dev/null || true
chown -R etluser:etlgroup /app/data_source 2>/dev/null || true

exec gosu etluser "$@"