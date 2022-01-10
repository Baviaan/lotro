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
        return self.converter(ctx.bot, ctx.guild.id, ctx.author.id, argument)

    @staticmethod
    def converter(bot, guild_id, author_id, argument):
        time_cog = bot.get_cog('TimeCog')
        parse_settings = {'PREFER_DATES_FROM': 'future'}
        argument_lower = argument.lower()
        server = _("server")
        if server in argument_lower:
            # Strip off server (time) and return as server time
            argument = argument_lower.partition(server)[0]
            parse_settings['TIMEZONE'] = time_cog.get_server_timezone(guild_id)
            parse_settings['RETURN_AS_TIMEZONE_AWARE'] = True
        time = dateparser.parse(argument, settings=parse_settings)
        if time is None:
            raise commands.BadArgument(_("Failed to parse time argument: ") + argument)
        if time.tzinfo is None:
            user_timezone = time_cog.get_user_timezone(author_id, guild_id)
            parse_settings['TIMEZONE'] = user_timezone
            parse_settings['RETURN_AS_TIMEZONE_AWARE'] = True
            tz = pytz.timezone(parse_settings['TIMEZONE'])
        else:
            tz = time.tzinfo
        # Parse again with time zone specific relative base as workaround for upstream issue
        # Upstream always checks if the time has passed in UTC, not in the specified timezone
        parse_settings['RELATIVE_BASE'] = datetime.datetime.now(tz=tz).replace(tzinfo=None)
        time = dateparser.parse(argument, settings=parse_settings)

        timestamp = int(time.timestamp())
        # Avoid scheduling event in the past
        if "now" in argument_lower:
            return timestamp+5
        return timestamp


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

    def get_user_timezone(self, user_id, guild_id):
        conn = self.bot.conn
        result = select_one(conn, 'Timezone', ['timezone'], ['player_id'], [user_id])
        if result is None:
            result = self.get_server_timezone(guild_id)
        return result

    def get_server_timezone(self, guild_id):
        conn = self.bot.conn
        result = select_one(conn, 'Settings', ['server'], ['guild_id'], [guild_id])
        if result is None:
            result = self.bot.server_tz
        return result


def setup(bot):
    bot.add_cog(TimeCog(bot))
    logger.info("Loaded Time Cog.")
