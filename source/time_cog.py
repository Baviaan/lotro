import dateparser
import datetime
import discord
import logging
import pytz

from discord import app_commands
from discord.ext import commands
from typing import Optional

from database import create_table, select_one, upsert
from utils import get_partial_matches

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

with open('common_timezones.txt', 'r') as f:
    common_timezones = f.read().splitlines()

with open('timezones.txt', 'r') as f:
    timezones = f.read().splitlines()

async def time_zone_autocomplete(interaction: discord.Interaction, current: str):
    tz_suggestions = common_timezones
    if current:
        query = get_partial_matches(current, timezones)
        if query:
            tz_suggestions = query
    return [
        app_commands.Choice(name=tz, value=tz)
        for tz in tz_suggestions
    ]


@app_commands.guild_only()
class TimeGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name=_("time_zones"), description=_("Manage time zone settings."))


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
        self.conn = bot.conn
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

    @app_commands.command(name=_("server_time"), description=_("Shows the current server time."))
    @app_commands.guild_only()
    async def server_time_respond(self, interaction: discord.Interaction):
        tz_str = self.get_server_timezone(interaction.guild_id)
        server_tz = pytz.timezone(tz_str)
        server_time = datetime.datetime.now(tz=server_tz)

        formatted_time = server_time.strftime("%A %H:%M")
        content = _("Current server time: {0}").format(formatted_time)
        await interaction.response.send_message(content)

    group = TimeGroup()

    @group.command(name=_("personal"), description=_("Set your time zone to be used when interpreting your raid commands."))
    @app_commands.describe(timezone=_("Select a city representing your time zone."))
    @app_commands.autocomplete(timezone=time_zone_autocomplete)
    async def time_zone_personal(self, interaction: discord.Interaction, timezone: Optional[str]):
        if timezone:
            try:
                tz = pytz.timezone(timezone)
            except pytz.UnknownTimeZoneError as e:
                content = _("{0} is not a valid time zone!").format(e)
                await interaction.response.send_message(content, ephemeral=True)
                return
            tz = str(tz)
            content = _("Set your time zone to {0}.").format(tz)
        else:
            tz = None
            content = _("Deleted your time zone data.")
        res = upsert(self.conn, 'Timezone', ['timezone'], [tz], ['player_id'], [interaction.user.id])
        self.conn.commit()
        await interaction.response.send_message(content, ephemeral=True)

    @group.command(name=_("server"), description=_("Set the time zone for this discord server."))
    @app_commands.describe(timezone=_("Select a city representing the time zone."))
    @app_commands.autocomplete(timezone=time_zone_autocomplete)
    async def time_zone_server(self, interaction: discord.Interaction, timezone: Optional[str]):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_("You must be an admin to change the server time zone."), ephemeral=True)
            return
        if timezone:
            try:
                tz = pytz.timezone(timezone)
            except pytz.UnknownTimeZoneError as e:
                content = _("{0} is not a valid time zone!").format(e)
                await interaction.response.send_message(content, ephemeral=True)
                return
            tz = str(tz)
            content = _("Set server time zone to {0}.").format(tz)
        else:
            tz = None
            content = _("Deleted server time zone data.")
        res = upsert(self.conn, 'Settings', ['server'], [tz], ['guild_id'], [interaction.guild_id])
        self.conn.commit()
        await interaction.response.send_message(content, ephemeral=True)


async def setup(bot):
    await bot.add_cog(TimeCog(bot))
    logger.info("Loaded Time Cog.")
