import logging
import sqlite3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def create_connection(db_file):
    """ create a database connection to a SQLite database """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except sqlite3.Error as e:
        logger.warning(e)
    return conn


def create_table(conn, sql, columns=None):
    """ create a table from the sql statement """
    if columns is None:
        columns = []
    sql_dict = {
        'raid': sql_raid_table(),
        'player': sql_player_table(columns),
        'assign': sql_assign_table(),
        'timezone': sql_timezone_table(),
        'settings': sql_settings_table()
    }
    sql = sql_dict[sql]
    try:
        c = conn.cursor()
        c.execute(sql)
    except sqlite3.Error as e:
        logger.warning(e)


def sql_raid_table():
    sql = """ create table if not exists Raids (
        raid_id integer primary key,
        channel_id integer not null,
        guild_id integer not null,
        organizer_id integer,
        name text not null,
        tier text not null,
        boss text not null,
        time integer not null,
        roster boolean not null
        ); """
    return sql


def sql_player_table(role_names):
    class_columns = ""
    for column in role_names:
        class_columns = class_columns + column + " boolean,"
    sql = """ create table if not exists Players (
        raid_id integer not null,
        player_id integer not null,
        byname text not null,
        unavailable boolean,
        """ + class_columns + """
        primary key(raid_id, player_id),
        foreign key (raid_id) references Raids(raid_id)
        );"""
    return sql


def sql_assign_table():
    sql = """ create table if not exists Assignment (
        raid_id integer not null,
        slot_id integer not null,
        player_id integer,
        byname text,
        class_name text,
        primary key(raid_id, slot_id),
        foreign key (raid_id) references Raids(raid_id)
        );"""
    return sql


def sql_timezone_table():
    sql = """ create table if not exists Timezone (
            player_id integer,
            timezone text,
            primary key(player_id)
            );"""
    return sql


def sql_settings_table():
    sql = """ create table if not exists Settings (
            guild_id integer,
            server text,
            display text[],
            prefix text,
            raid_leader text,
            calendar text,
            primary key(guild_id)
            );"""
    return sql


def add_timezone(conn, user_id, timezone):
    """ insert or update user's default timezone into the timezone table """
    sql = """ update Timezone set timezone=? where player_id=?;"""
    try:
        c = conn.cursor()
        c.execute(sql, (timezone, user_id))
        if c.rowcount == 0:
            sql = """ insert into Timezone(player_id, timezone) values(?,?); """
            c.execute(sql, (user_id, timezone))
        return True
    except sqlite3.Error as e:
        logger.warning(e)


def remove_timezone(conn, user_id):
    """ Delete user's default timezone in the timezone table """
    sql = """ delete from Timezone where player_id=?;"""
    try:
        c = conn.cursor()
        c.execute(sql, (user_id,))  # This needs a tuple.
        return True
    except sqlite3.Error as e:
        logger.warning(e)


def add_setting(conn, column, guild_id, value):
    """ insert or update guild's setting """
    sql = " update Settings set " + column + "=? where guild_id=?;"
    try:
        c = conn.cursor()
        c.execute(sql, (value, guild_id))
        if c.rowcount == 0:
            sql = " insert into Settings(guild_id, " + column + ") values(?,?); "
            c.execute(sql, (guild_id, value))
        return True
    except sqlite3.Error as e:
        logger.warning(e)


def remove_setting(conn, column, guild_id):
    """ Delete guild's setting """
    sql = "update Settings set " + column + "=NULL where guild_id=?;"
    try:
        c = conn.cursor()
        c.execute(sql, (guild_id,))  # This needs a tuple.
        return True
    except sqlite3.Error as e:
        logger.warning(e)


def add_raid(conn, raid):
    """ insert new raid into the raids table """
    sql = """ insert into Raids(raid_id, channel_id, guild_id, organizer_id, name, tier, boss, time, roster)
              values(?,?,?,?,?,?,?,?,?); """
    try:
        c = conn.cursor()
        c.execute(sql, raid)
    except sqlite3.Error as e:
        logger.warning(e)


def add_player_class(conn, raid, player, byname, player_classes, unavailable=0):
    """ insert or update player into players table """
    sql = "update Players set "
    for player_class in player_classes:
        sql = sql + player_class + "=1, "
    sql = sql + "unavailable={0}".format(unavailable)
    sql = sql + " where raid_id=? and player_id=?;"
    try:
        c = conn.cursor()
        c.execute(sql, (raid, player))
        if c.rowcount == 0:
            sql_columns = "insert into Players (raid_id, player_id, byname, unavailable"
            sql_values = "values (?,?,?,{0}".format(unavailable)
            for player_class in player_classes:
                sql_columns = sql_columns + ", " + player_class
                sql_values = sql_values + ",1"
            sql = sql_columns + ") " + sql_values + ");"
            c.execute(sql, (raid, player, byname))
    except sqlite3.Error as e:
        logger.warning(e)


def assign_player(conn, raid, slot, player_id, player_name, class_name):
    """ insert or update player into assignment table """
    sql = "update Assignment set player_id=?, byname=?, class_name=? where raid_id=? and slot_id=?;"
    try:
        c = conn.cursor()
        c.execute(sql, (player_id, player_name, class_name, raid, slot))
        if c.rowcount == 0:
            sql = "insert into Assignment(raid_id, slot_id, player_id, byname, class_name) values (?,?,?,?,?)"
            c.execute(sql, (raid, slot, player_id, player_name, class_name))
    except sqlite3.Error as e:
        logger.warning(e)

def select_players(conn, columns, raid_id, unavailable=0):
    """ returns database rows with columns from Players """
    sql = "select " + columns + " from Players where raid_id=? and unavailable=?;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (raid_id, unavailable))
        result = c.fetchall()
    except sqlite3.Error as e:
        logger.warning(e)
    return result

def count_players(conn, raid_id, unavailable=0):
    """ returns number of players """
    sql = "select count(player_id) from Players where raid_id=? and unavailable=?;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (raid_id, unavailable))
        result = c.fetchone()
    except sqlite3.Error as e:
        logger.warning(e)
    return result[0]


def select(conn, table, column, where=None):
    """ return column from table in the database """
    result = None
    try:
        c = conn.cursor()
        if where:
            sql = "select " + column + " from " + table + " where raid_id=?;"
            c.execute(sql, (where,))  # This needs a tuple.
        else:
            sql = "select " + column + " from " + table + ";"
            c.execute(sql)
        result = c.fetchall()
    except sqlite3.Error as e:
        logger.warning(e)
    return [i[0] for i in result]


def select_one(conn, table, column, primary_key, pk_column='raid_id'):
    """ return one field in column from table in the database """
    sql = "select " + column + " from " + table + " where " + pk_column + "=?;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (primary_key,))  # This needs a tuple.
        result = c.fetchone()
        if result:
            result = result[0]
    except sqlite3.Error as e:
        logger.warning(e)
    return result


def select_one_player(conn, table, column, player_id, raid_id):
    """ return one field in column from table in the database with player constraint """
    sql = "select " + column + " from " + table + " where player_id=? and raid_id=?;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (player_id, raid_id))
        result = c.fetchone()
        if result:
            result = result[0]
    except sqlite3.Error as e:
        logger.warning(e)
    return result


def select_one_slot(conn, raid_id, class_search):
    """ return one field in slot_id from assignment in the database with class constraint """
    sql = "select slot_id from Assignment where raid_id=? and player_id is null and class_name like ?;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (raid_id, class_search))
        result = c.fetchone()
        if result:
            result = result[0]
    except sqlite3.Error as e:
        logger.warning(e)
    return result


def select_rows(conn, table, columns, where):
    """ returns database rows with columns from table """
    sql = "select " + columns + " from " + table + " where raid_id=?;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (where,))  # This needs a tuple.
        result = c.fetchall()
    except sqlite3.Error as e:
        logger.warning(e)
    return result


def count_rows(conn, table, where):
    """ returns number of rows from table in database """
    sql = "select count() from " + table + " where guild_id=?;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (where,))  # This needs a tuple.
        result = c.fetchone()
    except sqlite3.Error as e:
        logger.warning(e)
    return result[0]


def delete_row(conn, table, primary_key):
    """ delete row from table in the database """
    sql = "delete from " + table + " where raid_id=?;"
    try:
        c = conn.cursor()
        c.execute(sql, (primary_key,))
    except sqlite3.Error as e:
        logger.warning(e)


def update_raid(conn, table, column, value, where):
    """ update column from table in the database """
    sql = "update " + table + " set " + column + "=? where raid_id=?;"
    try:
        c = conn.cursor()
        c.execute(sql, (value, where))
    except sqlite3.Error as e:
        logger.warning(e)


def delete_raid_player(conn, player_id, raid_id):
    """ delete player from table in the database """
    sql = "delete from Players where player_id=? and raid_id=?;"
    try:
        c = conn.cursor()
        c.execute(sql, (player_id, raid_id))
    except sqlite3.Error as e:
        logger.warning(e)


def select_two_columns(conn, column1, column2, table):
    """ returns database rows with columns from table """
    sql = "select " + column1 + ", " + column2 + " from " + table + ";"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql)
        result = c.fetchall()
    except sqlite3.Error as e:
        logger.warning(e)
    return result


def select_raids(conn, columns, guild_id):
    """ returns columns from raid table for guild """
    sql = "select " + columns + " from Raids where guild_id=? order by time;"
    result = None
    try:
        c = conn.cursor()
        c.execute(sql, (guild_id,))
        result = c.fetchall()
    except sqlite3.Error as e:
        logger.warning(e)
    return result
