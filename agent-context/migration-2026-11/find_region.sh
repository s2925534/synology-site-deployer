#!/bin/bash
set -uo pipefail
DEP=/Users/pedro/Documents/_Projects/synology-site-deployer/.env
getk(){ grep -m1 -E "^$1=" "$DEP" | sed -E "s/^$1=//" | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }
REF=$(getk SUPEBASE_CLOUD_ZQX_PROJECT_ID)
export PGPASSWORD=$(getk SUPEBASE_CLOUD_ZQX_DB_PWD)
export PGCONNECT_TIMEOUT=6 PGSSLMODE=require
REGIONS="us-east-1 us-east-2 us-west-1 us-west-2 ca-central-1 sa-east-1 ap-southeast-1 ap-southeast-2 ap-northeast-1 ap-northeast-2 ap-south-1 eu-west-1 eu-west-2 eu-west-3 eu-central-1 eu-central-2 eu-north-1"
for r in $REGIONS; do
  for p in aws-0 aws-1; do
    H="$p-$r.pooler.supabase.com"
    ERR=$(psql "host=$H port=5432 user=postgres.$REF dbname=postgres sslmode=require" -tAc "select 1" 2>&1)
    case "$ERR" in
      1) echo ">>> MATCH host=$H region=$r"; echo "$H" > /tmp/zqx_poolhost.txt; exit 0;;
      *"not found"*|*"Tenant or user not found"*) : ;;         # wrong region
      *"password"*) echo "    AUTH-REACHED (wrong pwd?) at $H"; ;;  # right region, pwd issue
      *) echo "    $H -> ${ERR##*FATAL:  }";;
    esac
  done
done
echo "NO MATCH across full region list"