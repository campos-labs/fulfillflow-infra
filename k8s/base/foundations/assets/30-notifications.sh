#!/bin/sh
set -eu

# Derived from frozen application infrastructure/init-notifications-db.sh. Fresh volume only.
psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 <<'SQL'
\getenv notifications_password NOTIFICATIONS_DB_PASSWORD
CREATE ROLE fulfillflow_notifications LOGIN PASSWORD :'notifications_password';
CREATE DATABASE fulfillflow_notifications OWNER fulfillflow_notifications;
REVOKE ALL ON DATABASE fulfillflow_notifications FROM PUBLIC;
SQL
