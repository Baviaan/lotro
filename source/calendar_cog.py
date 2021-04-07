import dateparser
import discord
import logging
import pytz
import re
import requests

from datetime import datetime, timedelta
from discord.ext import commands

from database import select_one, select_order, upsert
from TLSAdapter import ECDHEAdapter
from utils import chunks

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CalendarCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.time_cog = bot.get_cog('TimeCog')
        self.upcoming_events = None
        self.cached_events_at = None

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

    @commands.command()
    async def calendar(self, ctx):
        """ Sets the channel to post the calendar in. """
        if not await self.is_raid_leader(ctx):
            return
        conn = self.bot.conn
        try:
            await ctx.message.delete()
        except discord.Forbidden as e:
            logger.info(e)
        embed = self.calendar_embed(ctx.guild.id)
        msg = await ctx.send(embed=embed)
        ids = "{0}/{1}".format(ctx.channel.id, msg.id)
        res = upsert(conn, 'Settings', ['calendar'], [ids], ['guild_id'], [ctx.guild.id])
        if res:
            conn.commit()
            await ctx.send(_("The Calendar will be updated in this channel."), delete_after=20)
        else:
            await ctx.send(_("An error occurred."))
        return

    async def update_calendar(self, guild_id, new_run=True):
        conn = self.bot.conn
        res = select_one(conn, 'Settings', ['calendar'], ['guild_id'], [guild_id])
        if not res:
            return
        result = res.split("/")
        chn_id = int(result[0])
        msg_id = int(result[1])
        chn = self.bot.get_channel(chn_id)
        try:
            msg = chn.get_partial_message(msg_id)
        except (AttributeError, discord.NotFound):
            logger.warning("Calendar post not found for guild {0}.".format(guild_id))
            res = upsert(conn, 'Settings', ['calendar'], [None], ['guild_id'], [guild_id])
            if res:
                conn.commit()
            return

        embed = self.calendar_embed(guild_id)
        try:
            await msg.edit(embed=embed)
        except discord.HTTPException:
            logger.warning("Failed to update calendar for guild {0}.".format(guild_id))
            return
        except discord.Forbidden:
            logger.warning("Calendar access restricted for guild {0}.".format(guild_id))
            return
        if new_run:
            try:
                await chn.send(_("A new run has been posted!"), delete_after=3600)
            except discord.Forbidden:
                logger.warning("No write access to calendar channel for guild {0}.".format(guild_id))


    def calendar_embed(self, guild_id):
        time_cog = self.bot.get_cog('TimeCog')
        conn = self.bot.conn
        server_tz = time_cog.get_server_time(guild_id)
        raids = select_order(conn, 'Raids', ['channel_id', 'raid_id', 'name', 'tier', 'time'], 'time', ['guild_id'],
                             [guild_id])

        title = _("Scheduled runs:")
        desc = _("Time displayed in server time.\nClick the link to sign up!")
        embed = discord.Embed(title=title, description=desc, colour=discord.Colour(0x3498db))
        fmt_24hr = time_cog.get_24hr_fmt(guild_id)
        for raid in raids[:20]:
            timestamp = int(raid[4])
            time = datetime.utcfromtimestamp(timestamp)
            server_time = time_cog.local_time(time, server_tz)
            time_string = time_cog.calendar_time(server_time, fmt_24hr)
            msg = "[{name} {tier}](<https://discord.com/channels/{guild}/{channel}/{msg}>)\n".format(
                guild=guild_id, channel=raid[0], msg=raid[1], name=raid[2], tier=raid[3])
            embed.add_field(name=time_string, value=msg, inline=False)
        time = datetime.utcnow()
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = time
        return embed

    def get_events(self):
        current_time  = datetime.now(pytz.timezone("America/New_York"))
        if self.cached_events_at and self.cached_events_at > current_time - timedelta(days=1):
            return self.upcoming_events

        s = requests.Session()
        s.mount("https://www.lotro.com", ECDHEAdapter())
        r = s.get("https://www.lotro.com/forums/showthread.php?646193-LOTRO-Events-Schedule&s=37ca62f1171274310d6709145d372d3f&p=7646830#post7646830")
        if not r.ok:
            logger.warning("Could not connect to lotro.com")
            return self.upcoming_events

        stripped = re.sub('<[^<]+?>', '', r.text)
        # Let us hope this questionable pattern is stable enough
        pattern = 'Here is the current events schedule(.*)End Time:(.*)For the most up-to-date listings of player-run events'
        prog = re.compile(pattern, flags=re.DOTALL)
        result = prog.search(stripped)
        data  = [line for line in result.group(2).splitlines() if line]
        events = [chunk for chunk in chunks(data, 3)]
        parsed_events = [(event[0], *self.parse_event_time(*event[1:])) for event in events]

        cutoff_past = current_time - timedelta(days=1)
        cutoff_future = current_time + timedelta(days=90)
        upcoming_events = [event for event in parsed_events if cutoff_past < event[2] < cutoff_future]
        self.cached_events_at = current_time
        self.upcoming_events = upcoming_events
        return upcoming_events

    def event_embed(self, user_id, guild_id):
        events = self.get_events()

        time_cog = self.time_cog
        fmt_24hr = time_cog.get_24hr_fmt(guild_id)
        timezone = time_cog.get_user_timezone(user_id, guild_id)
        tz = pytz.timezone(timezone)
        city = timezone.rpartition("/")[2]

        title = _("Upcoming events:")
        desc = _("All times for {0}.").format(city)
        embed = discord.Embed(title=title, description=desc, colour=discord.Colour(0x3498db))
        for e in events:
            time_str = "{0} -- {1}".format(*self.format_event_time(*e[1:], tz, fmt_24hr))
            embed.add_field(name=e[0], value=time_str, inline=False)
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = self.cached_events_at
        return embed

    def parse_event_time(self, start, end):
        useastern = pytz.timezone("America/New_York")
        start = useastern.localize(dateparser.parse(start))
        end = useastern.localize(dateparser.parse(end))
        return start, end

    def format_event_time(self, start, end, tz, fmt_24hr):
        start = self.time_cog.calendar_time(start.astimezone(tz), fmt_24hr)
        end = self.time_cog.calendar_time(end.astimezone(tz), fmt_24hr)
        return start, end


def setup(bot):
    bot.add_cog(CalendarCog(bot))
    logger.info("Loaded Calendar Cog.")
