import dateparser
import datetime
import json
import logging
import os
import pytz

from discord.ext import commands

from database import add_setting, add_timezone, create_connection, create_table, \
    remove_timezone, select_one
from role_cog import get_role

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Time(commands.Converter):
    async def convert(self, ctx, argument):
        return await self.converter(ctx.channel, ctx.author, argument)

    @staticmethod
    async def converter(channel, author, argument):
        my_settings = {'PREFER_DATES_FROM': 'future'}
        argument = argument.lower()
        server = _("server")
        if server in argument:
            # Strip off server (time) and return as server time
            argument = argument.partition(server)[0]
            my_settings['TIMEZONE'] = TimeCog.get_server_time(author.guild.id)
            my_settings['RETURN_AS_TIMEZONE_AWARE'] = True
        time = dateparser.parse(argument, settings=my_settings)
        if time is None:
            raise commands.BadArgument(_("Failed to parse time argument: ") + argument)
        if time.tzinfo is None:
            user_timezone = TimeCog.get_user_timezone(author)
            my_settings['TIMEZONE'] = user_timezone
            my_settings['RETURN_AS_TIMEZONE_AWARE'] = True
            tz = pytz.timezone(my_settings['TIMEZONE'])
        else:
            tz = time.tzinfo
        # Parse again with time zone specific relative base as workaround for upstream issue
        # Upstream always checks if the time has passed in UTC, not in the specified timezone
        my_settings['RELATIVE_BASE'] = datetime.datetime.now().astimezone(tz).replace(tzinfo=None)
        time = dateparser.parse(argument, settings=my_settings)

        time = TimeCog.local_time(time, 'Etc/UTC')
        time = time.replace(tzinfo=None)  # Strip tz info
        # Check if time is in near future. Otherwise parsed date was likely unintended.
        current_time = datetime.datetime.utcnow()
        delta_time = datetime.timedelta(days=7)
        if current_time + delta_time < time:
            error_message = _("Please check the date {0}. You are posting a raid for: ").format(author.mention)\
                            + str(time) + " UTC"
            await channel.send(error_message, delete_after=30)
        return time


def is_raid_leader(conn):
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        raid_leader_name = select_one(conn, 'Settings', 'raid_leader', ctx.guild.id, 'guild_id')
        if not raid_leader_name:
            raid_leader_name = TimeCog.raid_leader_name
        raid_leader = await get_role(ctx.guild, raid_leader_name)
        if raid_leader in ctx.author.roles:
            return True
        if ctx.invoked_with == 'help':  # Do not ask me why it executes this check for the help command.
            return False
        error_msg = _("You do not have permission to change the raid settings. "
                      "You need to have the '{0}' role.").format(TimeCog.raid_leader_name)
        logger.info("Putting {0} on the naughty list.".format(ctx.author.name))
        await ctx.send(error_msg, delete_after=15)
        return False
    return commands.check(predicate)


class TimeCog(commands.Cog):
    with open('config.json', 'r') as f:
        config = json.load(f)

    # Get server timezone
    server_tz = config['SERVER_TZ']
    # Get display times
    display_times = config['TIMEZONES']
    # Get command prefix
    prefix = config['PREFIX']
    # Get raid leader role name
    raid_leader_name = config['LEADER']

    conn = create_connection('raid_db')
    if conn:
        logger.info("TimeCog connected to raid database.")
        create_table(conn, 'timezone')
    else:
        logger.error("TimeCog could not create database connection!")

    def cog_unload(self):
        pass

    timezone_brief = _("Sets the user's default timezone to be used for raid commands.")
    timezone_description = _("This command allows a user to set their default timezone to be used to interpret "
                             "commands issued by them. This setting will only apply to that specific user. Timezone "
                             "is to be provided in the tz database format. See "
                             "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
                             "\nYou can delete your stored timezone information by providing 'delete' as argument.")
    timezone_example = _("Examples:\n{0}timezone Australia/Sydney\n{0}timezone Europe/London\n{0}timezone "
                         "America/New_York").format(prefix)

    @commands.command(help=timezone_example, brief=timezone_brief, description=timezone_description)
    async def timezone(self, ctx, timezone):
        """Sets the user's default timezone to be used for raid commands."""
        delete = _("delete")
        reset = _("reset")
        default = _("default")
        if timezone in [delete, reset, default]:
            res = remove_timezone(self.conn, ctx.author.id)
            if res:
                self.conn.commit()
                await ctx.send(_("Deleted timezone information for {0}.").format(ctx.author.mention))
            else:
                await ctx.send(_("An error occurred."))
            return
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError as e:
            await ctx.send(str(e) + _(" is not a valid timezone!"))
        else:
            tz = str(tz)
            res = add_timezone(self.conn, ctx.author.id, tz)
            if res:
                self.conn.commit()
                await ctx.send(_("Set default timezone for {0} to {1}.").format(ctx.author.mention, tz))
            else:
                await ctx.send(_("An error occurred."))
        return

    servertime_brief = _("Sets the server time to be used in this guild.")
    servertime_description = _("This command allows a user overwrite the timezone for their game server. Timezone "
                               "is to be provided in the tz database format. See "
                               "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
    servertime_example = _("Examples:\n{0}servertime Australia/Sydney\n{0}servertime Europe/London\n{0}servertime "
                           "America/New_York").format(prefix)

    @commands.command(help=servertime_example, brief=servertime_brief, description=servertime_description)
    @is_raid_leader(conn)
    async def servertime(self, ctx, timezone):
        """Sets the timezone to be displayed as server time."""
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError as e:
            await ctx.send(str(e) + _(" is not a valid timezone!"))
        else:
            tz = str(tz)
            res = add_setting(self.conn, 'server', ctx.guild.id, tz)
            if res:
                self.conn.commit()
                await ctx.send(_("Set server time to {0}.").format(tz))
            else:
                await ctx.send(_("An error occurred."))
        return

    displaytime_brief = _("Sets the display times to be used in raid posts for this guild.")
    displaytime_description = _("This command allows a user overwrite the timezones displayed in raid posts. Timezone "
                                "is to be provided in the tz database format. See "
                                "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
    displaytime_example = _("Examples:\n{0}displaytimes Australia/Sydney Australia/Adelaide Australia/Perth\n"
                            "{0}displaytimes Europe/London Europe/Amsterdam\n"
                            "{0}displaytimes Europe/London America/New_York America/Los_Angeles").format(prefix)

    @commands.command(help=displaytime_example, brief=displaytime_brief, description=displaytime_description)
    @is_raid_leader(conn)
    async def displaytimes(self, ctx, *timezones):
        """Sets additional timezones to be displayed."""
        tzs = []
        for timezone in timezones:
            try:
                tz = pytz.timezone(timezone)
            except pytz.UnknownTimeZoneError as e:
                await ctx.send(str(e) + _(" is not a valid timezone!"))
            else:
                tzs.append(str(tz))
        if tzs:
            tz_string = ''
            for timezone in tzs:
                tz_string = tz_string + timezone + ','
            tz_string = tz_string[:-1]
            res = add_setting(self.conn, 'display', ctx.guild.id, tz_string)
            if res:
                self.conn.commit()
                msg_content = _("Set display times to: ")
                for tz in tzs:
                    msg_content = msg_content + tz + ", "
                msg_content = msg_content[:-2] + "."
                await ctx.send(msg_content)
            else:
                await ctx.send(_("An error occurred."))
        else:
            await ctx.send(_("Please provide a time zone argument!"))
        return

    fmt_brief = _("Set time to 12h or 24h format.")
    fmt_description = _("Specifies whether the bot displays time in 12h or 24h format.")
    fmt_example = _("Examples:\n{0}format 12\n{0}format 24").format(prefix)

    @commands.command(help=fmt_example, brief=fmt_brief, description=fmt_description)
    @is_raid_leader(conn)
    async def format(self, ctx, fmt):
        """Sets time to 12h or 24h format for the guild"""
        if fmt in ['24', '24h']:
            fmt_24hr = True
        elif fmt in ['12', '12h']:
            fmt_24hr = False
        else:
            await ctx.send(_("Please specify '12' or '24' when using this command."))
            return
        res = add_setting(self.conn, 'fmt_24hr', ctx.guild.id, fmt_24hr)
        if res:
            self.conn.commit()
            await ctx.send(_("Set server to use {0}h time format.").format(fmt[0:2]))
        else:
            await ctx.send(_("An error occurred."))

    @staticmethod
    def get_user_timezone(author):
        result = select_one(TimeCog.conn, 'Timezone', 'timezone', author.id, pk_column='player_id')
        if result is None:
            result = TimeCog.get_server_time(author.guild.id)
        return result

    @staticmethod
    def get_display_times(guild_id):
        result = select_one(TimeCog.conn, 'Settings', 'display', guild_id, pk_column='guild_id')
        if result is None:
            result = TimeCog.display_times
        else:
            result = result.split(',')
        return result

    @staticmethod
    def get_server_time(guild_id):
        result = select_one(TimeCog.conn, 'Settings', 'server', guild_id, pk_column='guild_id')
        if result is None:
            result = TimeCog.server_tz
        return result

    @staticmethod
    def format_time(time, guild_id):
        fmt_24hr = select_one(TimeCog.conn, 'Settings', 'fmt_24hr', guild_id, pk_column='guild_id')
        if fmt_24hr:
            time_string = time.strftime("%A %H:%M")
        else:
            if os.name == "nt":  # Windows uses '#' instead of '-'.
                time_string = time.strftime("%A %#I:%M %p")
            else:
                time_string = time.strftime("%A %-I:%M %p")
        return time_string

    @staticmethod
    def calendar_time(time, guild_id):
        fmt_24hr = select_one(TimeCog.conn, 'Settings', 'fmt_24hr', guild_id, pk_column='guild_id')
        if fmt_24hr:
            time_string = time.strftime("%b %d, %A %H:%M")
        else:
            if os.name == "nt":  # Windows uses '#' instead of '-'.
                time_string = time.strftime(_("%b %d, %A %#I:%M %p"))
            else:
                time_string = time.strftime(_("%b %d, %A %-I:%M %p"))
        return time_string

    @staticmethod
    def local_time(time, timezone):
        if not time.tzinfo:
            time = pytz.utc.localize(time)  # time is stored as UTC
        tz = pytz.timezone(timezone)
        local_time = time.astimezone(tz)  # Convert to local time
        return local_time


def setup(bot):
    bot.add_cog(TimeCog(bot))
    logger.info("Loaded Time Cog.")
