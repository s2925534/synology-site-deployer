#!/usr/bin/env bash
# Enable OFFSITE backups for the velosolabs AWS box.
#
# The nightly backup on velosolabs-prod (/home/ubuntu/velosolabs/backup.sh, cron 02:17 UTC)
# already dumps hub-SQLite + box-mariadb + box-postgres + Neon-gateway locally and keeps 14 days.
# It uploads to S3 ONLY once BACKUP_S3_* creds exist in the box ~/velosolabs/.env. This script
# mints the least-privilege IAM user that the auto-mode classifier would not let an agent create,
# then writes those creds onto the box so offsite uploads begin on the next run.
#
# Bucket velosolabs-backups (ap-southeast-2) already exists, hardened: SSE-S3, versioning,
# public-access blocked, lifecycle (daily/ 90d + noncurrent 30d, forensics/ 365d).
#
# Run from repo root:  ! bash agent-context/ops/setup-backups-s3-iam.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
ENVF=.env
KID=$(grep -E '^AWS_DEST_ACCESS_KEY_ID=' "$ENVF" | head -1 | cut -d= -f2-)
SEC=$(grep -E '^AWS_DEST_SECRET_ACCESS_KEY=' "$ENVF" | head -1 | cut -d= -f2-)
AWS=/opt/homebrew/bin/aws
B=velosolabs-backups
U=velosolabs-backup
r(){ env -i PATH="/usr/bin:/bin:/opt/homebrew/bin" AWS_PAGER="" AWS_ACCESS_KEY_ID="$KID" AWS_SECRET_ACCESS_KEY="$SEC" AWS_DEFAULT_REGION=ap-southeast-2 "$AWS" --no-cli-pager "$@"; }

echo "acct: $(r sts get-caller-identity --query Account --output text) (expect 241088755146)"
r iam get-user --user-name "$U" >/dev/null 2>&1 && echo "user $U already exists" || \
  r iam create-user --user-name "$U" --query 'User.Arn' --output text
r iam put-user-policy --user-name "$U" --policy-name s3-backup-put --policy-document \
  "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"Put\",\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\"],\"Resource\":\"arn:aws:s3:::$B/*\"},{\"Sid\":\"List\",\"Effect\":\"Allow\",\"Action\":[\"s3:ListBucket\",\"s3:GetBucketLocation\"],\"Resource\":\"arn:aws:s3:::$B\"}]}"
echo "policy s3-backup-put attached (PutObject + ListBucket on $B only)"
OUT=$(r iam create-access-key --user-name "$U" --output json)
NKID=$(echo "$OUT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["AccessKey"]["AccessKeyId"])')
NSEC=$(echo "$OUT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["AccessKey"]["SecretAccessKey"])')
echo "new access key for $U: $NKID"

# ---- write BACKUP_S3_* onto the box ~/velosolabs/.env (fresh Lightsail SSH cert, inline) ----
TMP=$(mktemp -d)
env -i PATH="/usr/bin:/bin:/opt/homebrew/bin" AWS_PAGER="" AWS_ACCESS_KEY_ID="$KID" AWS_SECRET_ACCESS_KEY="$SEC" AWS_DEFAULT_REGION=ap-southeast-2 \
  "$AWS" --no-cli-pager lightsail get-instance-access-details --instance-name velosolabs-prod --protocol ssh --output json > "$TMP/a.json"
python3 - "$TMP" <<'PY'
import json,sys,os
d=json.load(open(sys.argv[1]+"/a.json"))["accessDetails"]
open(sys.argv[1]+"/k","w").write(d["privateKey"].strip()+"\n"); os.chmod(sys.argv[1]+"/k",0o600)
open(sys.argv[1]+"/k-cert.pub","w").write(d["certKey"].strip()+"\n"); os.chmod(sys.argv[1]+"/k-cert.pub",0o600)
PY
printf 'BACKUP_S3_ACCESS_KEY_ID=%s\nBACKUP_S3_SECRET_ACCESS_KEY=%s\nBACKUP_S3_BUCKET=%s\nBACKUP_S3_REGION=ap-southeast-2\n' "$NKID" "$NSEC" "$B" | \
  ssh -i "$TMP/k" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no ubuntu@3.106.236.248 \
    'cd /home/ubuntu/velosolabs && touch .env && grep -v "^BACKUP_S3_" .env > .env.new; cat >> .env.new; mv .env.new .env; chmod 600 .env; echo "box .env now has $(grep -c ^BACKUP_S3_ .env) BACKUP_S3_ lines"'
rm -rf "$TMP"
echo "DONE. Offsite uploads start on the next nightly run. Test now:"
echo "  (from the box)  cd ~/velosolabs && ./backup.sh   # expect 's3 upload: N file(s)'"
