import dateparser
import datetime
import logging
import pytz

from discord.ext import commands

from database import create_table, select_one

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
