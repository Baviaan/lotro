import dateparser
import datetime
import json
import logging
import os
import pytz

from discord.ext import commands

from database import create_table, delete, select_one, upsert

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Time(commands.Converter):
    async def convert(self, ctx, argument):
        return await self.converter(ctx.bot, ctx.channel, ctx.author.id, argument)

    @staticmethod
    async def converter(bot, channel, author_id, argument):
        time_cog = bot.get_cog('TimeCog')
        guild_id = channel.guild.id
        my_settings = {'PREFER_DATES_FROM': 'future'}
        argument_lower = argument.lower()
        server = _("server")
        if server in argument_lower:
            # Strip off server (time) and return as server time
            argument = argument_lower.partition(server)[0]
            my_settings['TIMEZONE'] = time_cog.get_server_time(guild_id)
            my_settings['RETURN_AS_TIMEZONE_AWARE'] = True
        time = dateparser.parse(argument, settings=my_settings)
        if time is None:
            raise commands.BadArgument(_("Failed to parse time argument: ") + argument)
        if time.tzinfo is None:
            user_timezone = time_cog.get_user_timezone(author_id, guild_id)
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
            error_message = _("Please check the date <@{0}>. You are posting a raid for: ").format(author_id) \
                            + str(time) + " UTC"
            await channel.send(error_message, delete_after=30)
        return time


class TimeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        create_table(self.bot.conn, 'timezone')

    with open('config.json', 'r') as f:
        config = json.load(f)
    prefix = config['PREFIX']

    tz_brief = _("Sets the user's default timezone to be used for raid commands.")
    tz_description = _("This command allows a user to set their default timezone to be used to interpret "
                       "commands issued by them. This setting will only apply to that specific user. Timezone "
                       "is to be provided in the tz database format. See "
                       "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
                       "\nYou can delete your stored timezone information by providing 'delete' as argument.")
    tz_example = _("Examples:\n{0}timezone Australia/Sydney\n{0}timezone Europe/London\n{0}timezone "
                   "America/New_York").format(prefix)

    servertime_brief = _("Sets the server time to be used in this guild.")
    servertime_description = _("This command allows a user overwrite the timezone for their game server. Timezone "
                               "is to be provided in the tz database format. See "
                               "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
    servertime_example = _("Examples:\n{0}servertime Australia/Sydney\n{0}servertime Europe/London\n{0}servertime "
                           "America/New_York").format(prefix)

    displaytime_brief = _("Sets the display times to be used in raid posts for this guild.")
    displaytime_description = _("This command allows a user overwrite the timezones displayed in raid posts. Timezone "
                                "is to be provided in the tz database format. See "
                                "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
    displaytime_example = _("Examples:\n{0}displaytimes Australia/Sydney Australia/Adelaide Australia/Perth\n"
                            "{0}displaytimes Europe/London Europe/Amsterdam\n"
                            "{0}displaytimes Europe/London America/New_York America/Los_Angeles").format(prefix)

    fmt_brief = _("Set time to 12h or 24h format.")
    fmt_description = _("Specifies whether the bot displays time in 12h or 24h format.")
    fmt_example = _("Examples:\n{0}format 12\n{0}format 24").format(prefix)

    async def is_raid_leader(self, ctx):
        conn = self.bot.conn
        if ctx.author.guild_permissions.administrator:
            return True
        raid_leader_id = select_one(conn, 'Settings', ['raid_leader'], ['guild_id'], [ctx.guild.id])
        if raid_leader_id in [role.id for role in ctx.author.roles]:
            return True
        error_msg = _("You do not have permission to change the settings.")
        await ctx.send(error_msg, delete_after=15)
        return False

    @commands.command(help=tz_example, brief=tz_brief, description=tz_description)
    async def timezone(self, ctx, timezone):
        """Sets the user's default timezone to be used for raid commands."""
        conn = self.bot.conn
        if timezone in [_("delete"), _("reset"), _("default")]:
            res = delete(conn, 'Timezone', ['player_id'], [ctx.author.id])
            if res:
                conn.commit()
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
            res = upsert(conn, 'Timezone', ['timezone'], [tz], ['player_id'], [ctx.author.id])
            if res:
                conn.commit()
                await ctx.send(_("Set default timezone for {0} to {1}.").format(ctx.author.mention, tz))
            else:
                await ctx.send(_("An error occurred."))
        return

    @commands.command(help=servertime_example, brief=servertime_brief, description=servertime_description)
    async def servertime(self, ctx, timezone):
        """Sets the timezone to be displayed as server time."""
        if not await self.is_raid_leader(ctx):
            return
        conn = self.bot.conn
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError as e:
            await ctx.send(str(e) + _(" is not a valid timezone!"))
        else:
            tz = str(tz)
            res = upsert(conn, 'Settings', ['server'], [tz], ['guild_id'], [ctx.guild.id])
            if res:
                conn.commit()
                await ctx.send(_("Set server time to {0}.").format(tz))
            else:
                await ctx.send(_("An error occurred."))
        return

    @commands.command(help=displaytime_example, brief=displaytime_brief, description=displaytime_description)
    async def displaytimes(self, ctx, *timezones):
        """Sets additional timezones to be displayed."""
        if not await self.is_raid_leader(ctx):
            return
        conn = self.bot.conn
        tzs = []
        for timezone in timezones:
            try:
                tz = pytz.timezone(timezone)
            except pytz.UnknownTimeZoneError as e:
                await ctx.send(str(e) + _(" is not a valid timezone!"))
            else:
                tzs.append(str(tz))
        if tzs:
            tz_string = ",".join(tzs)
            res = upsert(conn, 'Settings', ['display'], [tz_string], ['guild_id'], [ctx.guild.id])
            if res:
                conn.commit()
                msg_content = _("Set display times to: ") + ", ".join(tzs) + "."
                await ctx.send(msg_content)
            else:
                await ctx.send(_("An error occurred."))
        else:
            await ctx.send(_("Please provide a time zone argument!"))
        return

    @commands.command(help=fmt_example, brief=fmt_brief, description=fmt_description)
    async def format(self, ctx, fmt):
        """Sets time to 12h or 24h format for the guild"""
        if not await self.is_raid_leader(ctx):
            return
        conn = self.bot.conn
        if fmt in ['24', '24h']:
            fmt_24hr = True
        elif fmt in ['12', '12h']:
            fmt_24hr = False
        else:
            await ctx.send(_("Please specify '12' or '24' when using this command."))
            return
        res = upsert(conn, 'Settings', ['fmt_24hr'], [fmt_24hr], ['guild_id'], [ctx.guild.id])
        if res:
            conn.commit()
            await ctx.send(_("Set server to use {0}h time format.").format(fmt[0:2]))
        else:
            await ctx.send(_("An error occurred."))

    def get_user_timezone(self, user_id, guild_id):
        conn = self.bot.conn
        result = select_one(conn, 'Timezone', ['timezone'], ['player_id'], [user_id])
        if result is None:
            result = self.get_server_time(guild_id)
        return result

    def get_display_times(self, guild_id):
        conn = self.bot.conn
        result = select_one(conn, 'Settings', ['display'], ['guild_id'], [guild_id])
        if result is None:
            result = self.bot.display_times
        else:
            result = result.split(',')
        return result

    def get_server_time(self, guild_id):
        conn = self.bot.conn
        result = select_one(conn, 'Settings', ['server'], ['guild_id'], [guild_id])
        if result is None:
            result = self.bot.server_tz
        return result

    def get_24hr_fmt(self, guild_id):
        conn = self.bot.conn
        fmt_24hr = select_one(conn, 'Settings', ['fmt_24hr'], ['guild_id'], [guild_id])
        return fmt_24hr

    @staticmethod
    def format_time(time, fmt_24hr):
        if fmt_24hr:
            time_string = time.strftime("%A %H:%M")
        else:
            if os.name == "nt":  # Windows uses '#' instead of '-'.
                time_string = time.strftime("%A %#I:%M %p")
            else:
                time_string = time.strftime("%A %-I:%M %p")
        return time_string

    @staticmethod
    def calendar_time(time, fmt_24hr):
        if fmt_24hr:
            time_string = time.strftime(_("%b %d, %A %H:%M"))
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
