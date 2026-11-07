"""db_config.py -- single place holding the MySQL connection details.
All the databases (the 4 sources and the warehouse layers) live on this one
local server, each fully separate -- no cross-database foreign keys, because
the four sources were designed in isolation.
"""

import mysql.connector

MYSQL_HOST = "127.0.0.1"
MYSQL_USER = "iia_app"
MYSQL_PASSWORD = "iia_app_pw"


def connect(database):
    return mysql.connector.connect(
        host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD, database=database
    )
