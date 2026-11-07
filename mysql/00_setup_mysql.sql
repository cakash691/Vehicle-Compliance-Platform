-- 00_setup_mysql.sql -- run once (as root/admin) before loading any data.
-- Creates the application user and the databases: the 4 sources, the prototype's
-- warehouse (vehicle_dwh), and the warehouse layers (bronze, silver, gold, etl).
-- Safe to run again: nothing here drops or empties anything.
-- Usage: mysql -u root -p < mysql/00_setup_mysql.sql

CREATE USER IF NOT EXISTS 'iia_app'@'127.0.0.1' IDENTIFIED BY 'iia_app_pw';

-- the four source databases
CREATE DATABASE IF NOT EXISTS roadcapture;
CREATE DATABASE IF NOT EXISTS insurance;
CREATE DATABASE IF NOT EXISTS rto_registration;
CREATE DATABASE IF NOT EXISTS theft_records;

-- the prototype's warehouse (retired once gold.vehicle_360 exists)
CREATE DATABASE IF NOT EXISTS vehicle_dwh;

-- the warehouse layers (see docs/DATA_MODEL.md) and the run log
CREATE DATABASE IF NOT EXISTS bronze;
CREATE DATABASE IF NOT EXISTS silver;
CREATE DATABASE IF NOT EXISTS gold;
CREATE DATABASE IF NOT EXISTS etl;

GRANT ALL PRIVILEGES ON roadcapture.*       TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON insurance.*         TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON rto_registration.*  TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON theft_records.*     TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON vehicle_dwh.*       TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON bronze.*            TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON silver.*            TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON gold.*              TO 'iia_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON etl.*               TO 'iia_app'@'127.0.0.1';

FLUSH PRIVILEGES;
