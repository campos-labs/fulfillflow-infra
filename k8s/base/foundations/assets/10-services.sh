#!/bin/sh
set -eu

# Derived from frozen application infrastructure/init-databases.sh. Fresh volume only.
psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 <<'SQL'
\getenv core_password CORE_DB_PASSWORD
\getenv tracking_password TRACKING_DB_PASSWORD
CREATE ROLE fulfillflow_core LOGIN PASSWORD :'core_password';
CREATE ROLE fulfillflow_tracking LOGIN PASSWORD :'tracking_password';
CREATE DATABASE fulfillflow_core OWNER fulfillflow_core;
CREATE DATABASE fulfillflow_tracking OWNER fulfillflow_tracking;
REVOKE ALL ON DATABASE fulfillflow_core FROM PUBLIC;
REVOKE ALL ON DATABASE fulfillflow_tracking FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
SQL
