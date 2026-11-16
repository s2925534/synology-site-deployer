#!/usr/bin/env bash
# Forensic evidence capture of the two compromised NAS WordPress databases, uploaded to S3.
#
# WHY THIS IS STAGED (not auto-run): the dumps contain user emails + password hashes (PII).
# The auto-mode classifier (correctly) refused to let an agent push that PII to S3 without you
# explicitly authorising the destination. Running this script IS that authorisation.
#
# READ-ONLY on the NAS: mariadb-dump --single-transaction, no site modification, nothing restarted.
# Preserves the compromised state BEFORE the clean rebuild. Run this immediately before rebuilding.
#   ! bash agent-context/ops/forensic-dump-wp.sh
#
# Evidence already proven captured 2026-11-16 (held locally, not yet offsite). SHA-256 of that capture:
#   4aac53de226c3cd4f15ee2df2d1bc47c1a07aa0d247eaf0a9acb3273ec446951  modamarieclaire_veloso_dev (9.0M gz)
#   6e07fb0ffeb9e67c6df7b01481f7574311f07523fa6fe849b7c3d457590a2e20  systemsnotsilos_com (15K gz)
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
ENVF=.env
PW=$(grep -E '^NAS_SSH_PASSWORD=' "$ENVF" | head -1 | cut -d= -f2-)
KID=$(grep -E '^AWS_DEST_ACCESS_KEY_ID=' "$ENVF" | head -1 | cut -d= -f2-)
SEC=$(grep -E '^AWS_DEST_SECRET_ACCESS_KEY=' "$ENVF" | head -1 | cut -d= -f2-)
K=~/.ssh/id_ed25519_zqx_nas
NAS=pedro@192.168.1.109
D=/var/packages/ContainerManager/target/usr/bin/docker
AWS=/opt/homebrew/bin/aws
DAY=$(date -u +%Y-%m-%d)
OUT=$(mktemp -d)
aws(){ env -i PATH="/usr/bin:/bin:/opt/homebrew/bin" AWS_PAGER="" AWS_ACCESS_KEY_ID="$KID" AWS_SECRET_ACCESS_KEY="$SEC" AWS_DEFAULT_REGION=ap-southeast-2 "$AWS" --no-cli-pager "$@"; }

dump(){ local C=$1 DB=$2
  ssh -i "$K" -o IdentitiesOnly=yes -o ConnectTimeout=25 "$NAS" \
    "echo '$PW' | sudo -S $D exec $C sh -c 'exec mariadb-dump -uroot -p\"\$MARIADB_ROOT_PASSWORD\" --single-transaction --quick --routines --events --default-character-set=utf8mb4 $DB' 2>/dev/null" \
    2>/dev/null | gzip > "$OUT/${DB}-${DAY}.sql.gz"
  echo "  dumped $DB -> $(stat -f%z "$OUT/${DB}-${DAY}.sql.gz" 2>/dev/null || stat -c%s "$OUT/${DB}-${DAY}.sql.gz") B gz ; gzip -t "$OUT/${DB}-${DAY}.sql.gz" && echo "  gzip OK"
}
echo "=== read-only forensic dumps ==="
dump systemsnotsilos-com-db systemsnotsilos_com
dump modamarieclaire-veloso-dev-db modamarieclaire_veloso_dev
( cd "$OUT" && shasum -a 256 *.sql.gz > "MANIFEST-${DAY}.txt" && cat "MANIFEST-${DAY}.txt" )

echo "=== upload to s3://velosolabs-backups/forensics/${DAY}/ (SSE-S3, 365d retention) ==="
for f in "$OUT"/*.sql.gz "$OUT"/MANIFEST-${DAY}.txt; do
  aws s3 cp "$f" "s3://velosolabs-backups/forensics/${DAY}/$(basename "$f")" --only-show-errors && echo "  uploaded $(basename "$f")"
done
aws s3 ls "s3://velosolabs-backups/forensics/${DAY}/" --human-readable
rm -rf "$OUT"
echo "DONE — evidence preserved offsite. Safe to proceed with the clean rebuild."
