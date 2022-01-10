import json
import logging
import sqlite3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

with open('config.json', 'r') as f:
    config = json.load(f)
classes = config['CLASSES']
classes_str = " boolean, ".join(classes) + " boolean, "


def create_connection(db_file):
    """ create a database connection to a SQLite database """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except sqlite3.Error as e:
        logger.exception(e)
    return conn


def create_table(conn, table):
    """ create a database table """
    sql = table_sqls(table)
    try:
        c = conn.cursor()
        c.execute(sql)
    except sqlite3.Error as e:
        logger.exception(e)


def table_sqls(table):
    sql_dict = {
            'raid': "create table if not exists Raids ("
                    "raid_id integer primary key, "
                    "channel_id integer not null, "
                    "guild_id integer not null, "
                    "organizer_id integer not null, "
                    "event_id integer, "
                    "name text not null, "
                    "tier text, "
                    "boss text, "
                    "time integer not null, "
                    "roster boolean not null"
                    ");",

            'player': "create table if not exists Players ("
                      "raid_id integer not null, "
                      "player_id integer not null, "
                      "byname text not null, "
                      "timestamp integer, "
                      "unavailable boolean, "
                      "{0}"
                      "primary key (raid_id, player_id), "
                      "foreign key (raid_id) references Raids(raid_id)"
                      ");".format(classes_str),

            'assign': "create table if not exists Assignment ("
                      "raid_id integer not null, "
                      "slot_id integer not null, "
                      "player_id integer, "
                      "byname text, "
                      "class_name text, "
                      "primary key (raid_id, slot_id), "
                      "foreign key (raid_id) references Raids(raid_id)"
                      ");",

            'timezone': "create table if not exists Timezone ("
                        "player_id integer primary key, "
                        "timezone text"
                        ");",

            'settings': "create table if not exists Settings ("
                        "guild_id integer primary key, "
                        "server text, "
                        "prefix text, "
                        "raid_leader integer, "
                        "priority integer, "
                        "calendar text, "
                        "guild_events integer, "
                        "twitter integer, "
                        "last_command integer, "
                        "command_count integer, "
                        "slash_count integer"
                        ");",

            'twitter':  "create table if not exists Twitter ("
                        "user_id integer primary key,"
                        "tweet_id integer"
                        ");"
    }
    return sql_dict[table]


def upsert(conn, table, columns, values, where_columns=None, where_values=None):
    """ update or insert values """
    assert len(columns) == len(values)
    updates = ["update {0} set".format(table), ", ".join(["=".join([column, "?"]) for column in columns])]
    if where_columns:
        assert len(where_columns) == len(where_values)
        updates.append("where")
        updates.append(" and ".join(["=".join([column, "?"]) for column in where_columns]))
        update_values = values + where_values
    else:
        update_values = values
    updates.append(";")
    sql_update = " ".join(updates)
    try:
        c = conn.cursor()
        c.execute(sql_update, update_values)
        if c.rowcount == 0:
            if where_columns:
                insert_columns = columns + where_columns
                insert_values = values + where_values
            else:
                insert_columns = columns
                insert_values = values
            inserts = ["insert into {0} (".format(table), ", ".join(insert_columns), ") values (",
                       ", ".join("?" * len(insert_values)), ");"]
            sql_insert = " ".join(inserts)
            c.execute(sql_insert, insert_values)
        return True
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_update)

def increment(conn, table, column, where_columns=None, where_values=None):
    """ increment column value by 1 """
    increments = ["update {0} set {1} = ifnull({1}, 0) + 1".format(table, column)]
    if where_columns:
        assert len(where_columns) == len(where_values)
        increments.append("where")
        increments.append(" and ".join(["=".join([column, "?"]) for column in where_columns]))
    increments.append(";")
    sql_increment = " ".join(increments)
    try:
        c = conn.cursor()
        if where_values:
            c.execute(sql_increment, where_values)
        else:
            c.execute(sql_increment)
        return True
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_increment)


def delete(conn, table, where_columns, where_values):
    """ delete a record """
    deletes = ["delete from {0} where".format(table),
               " and ".join(["=".join([column, "?"]) for column in where_columns]), ";"]
    sql_delete = " ".join(deletes)
    try:
        c = conn.cursor()
        c.execute(sql_delete, where_values)
        return True
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_delete)


def select(conn, table, columns, where_columns=None, where_values=None):
    selects = ["select", ", ".join(columns), "from {0}".format(table)]
    if where_columns:
        assert len(where_columns) == len(where_values)
        selects.append("where")
        selects.append(" and ".join(["=".join([column, "?"]) for column in where_columns]))
    selects.append(";")
    sql_select = " ".join(selects)
    try:
        c = conn.cursor()
        if where_values:
            c.execute(sql_select, where_values)
        else:
            c.execute(sql_select)
        result = c.fetchall()
        return result
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_select)


def select_one(conn, table, columns, eq_columns=None, eq_values=None, none_columns=None, like_columns=None, like_values=None):
    selects = ["select", ", ".join(columns), "from {0}".format(table)]
    if eq_columns or none_columns or like_columns:
        selects.append("where")
        if eq_columns:
            assert len(eq_columns) == len(eq_values)
            selects.append(" and ".join(["=".join([column, "?"]) for column in eq_columns]))
        if eq_columns and none_columns:
            selects.append("and")
        if none_columns:
            selects.append(" and ".join([column + " is null" for column in none_columns]))
        if (eq_columns or none_columns) and like_columns:
            selects.append("and")
        if like_columns:
            assert len(like_columns) == len(like_values)
            selects.append(" and ".join([" like ".join([column, "?"]) for column in like_columns]))
    selects.append(";")
    sql_select = " ".join(selects)
    try:
        c = conn.cursor()
        if eq_values or like_values:
            if eq_values and like_values:
                values = eq_values + like_values
            elif eq_values:
                values = eq_values
            else:
                values = like_values
            c.execute(sql_select, values)
        else:
            c.execute(sql_select)
        result = c.fetchone()
        if result and len(result) == 1:
            return result[0]
        return result
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_select)


def select_order(conn, table, columns, order, where_columns=None, where_values=None):
    selects = ["select", ", ".join(columns), "from {0}".format(table)]
    if where_columns:
        assert len(where_columns) == len(where_values)
        selects.append("where")
        selects.append(" and ".join(["=".join([column, "?"]) for column in where_columns]))
    selects.append("order by {0};".format(order))
    sql_select = " ".join(selects)
    try:
        c = conn.cursor()
        if where_values:
            c.execute(sql_select, where_values)
        else:
            c.execute(sql_select)
        result = c.fetchall()
        return result
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_select)


def select_le(conn, table, columns, where_columns=None, where_values=None):
    selects = ["select", ", ".join(columns), "from {0}".format(table)]
    if where_columns:
        assert len(where_columns) == len(where_values)
        selects.append("where")
        selects.append(" and ".join(["<".join([column, "?"]) for column in where_columns]))
    selects.append(";")
    sql_select = " ".join(selects)
    try:
        c = conn.cursor()
        if where_values:
            c.execute(sql_select, where_values)
        else:
            c.execute(sql_select)
        result = c.fetchall()
        return result
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_select)


def count(conn, table, column, where_columns=None, where_values=None):
    counts = ["select count({1}) from {0}".format(table, column)]
    if where_columns:
        assert len(where_columns) == len(where_values)
        counts.append("where")
        counts.append(" and ".join(["=".join([column, "?"]) for column in where_columns]))
    counts.append(";")
    sql_count = " ".join(counts)
    try:
        c = conn.cursor()
        if where_values:
            c.execute(sql_count, where_values)
        else:
            c.execute(sql_count)
        result = c.fetchone()
        return result[0]
    except sqlite3.Error as e:
        logger.exception(e)
        logger.info(sql_count)
