import dateparser
import discord
import logging
import pytz
import re
import requests

from datetime import datetime, timedelta
from discord import app_commands
from discord.ext import commands

from database import select_one, select_order, upsert
from TLSAdapter import ECDHEAdapter
from utils import chunks

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@app_commands.guild_only()
class CalendarGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name=_("calendar"), description=_("Manage the calendar settings."))


class CalendarCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        self.time_cog = bot.get_cog('TimeCog')
        self.upcoming_events = None
        self.cached_events_at = None
        self.headers = {
            "Authorization": "Bot {0}".format(bot.token)
        }

    def is_raid_leader(self, user, guild):
        if user.guild_permissions.administrator:
            return True
        raid_leader_id = select_one(self.conn, 'Settings', ['raid_leader'], ['guild_id'], [guild.id])
        if raid_leader_id:
            raid_leader = guild.get_role(raid_leader_id)
            if raid_leader in user.roles:
                return True
        return False

    async def post_calendar(self, guild_id, channel):
        embed = self.calendar_embed(guild_id)
        msg = await channel.send(embed=embed)
        ids = "{0}/{1}".format(channel.id, msg.id)
        res = upsert(self.conn, 'Settings', ['calendar'], [ids], ['guild_id'], [guild_id])
        self.conn.commit()

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
        except AttributeError:
            logger.warning("Calendar channel not found for guild {0}.".format(guild_id))
            res = upsert(conn, 'Settings', ['calendar'], [None], ['guild_id'], [guild_id])
            if res:
                conn.commit()
            return

        embed = self.calendar_embed(guild_id)
        try:
            await msg.edit(embed=embed)
        except discord.Forbidden:
            logger.warning("Calendar access restricted for guild {0}.".format(guild_id))
            return
        except discord.NotFound:
            logger.warning("Calendar post not found for guild {0}.".format(guild_id))
            upsert(conn, 'Settings', ['calendar'], [None], ['guild_id'], [guild_id])
            conn.commit()
            return
        except discord.HTTPException as e:
            logger.warning("Failed to update calendar for guild {0}.".format(guild_id))
            logger.warning(e)
            return
        if new_run:
            try:
                await chn.send(_("A new run has been posted!"), delete_after=3600)
            except discord.Forbidden:
                logger.warning("No write access to calendar channel for guild {0}.".format(guild_id))

    def calendar_embed(self, guild_id):
        conn = self.bot.conn
        raids = select_order(conn, 'Raids', ['channel_id', 'raid_id', 'name', 'tier', 'time'], 'time', ['guild_id'],
                             [guild_id])

        title = _("Scheduled runs:")
        desc = _("Click the link to sign up!")
        embed = discord.Embed(title=title, description=desc, colour=discord.Colour(0x3498db))
        for raid in raids[:20]:
            timestamp = int(raid[4])
            msg = "[{name} {tier}](<https://discord.com/channels/{guild}/{channel}/{msg}>)\n".format(
                guild=guild_id, channel=raid[0], msg=raid[1], name=raid[2], tier=raid[3])
            embed.add_field(name=f"<t:{timestamp}:F>", value=msg, inline=False)
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = datetime.now()
        return embed

    def create_guild_event(self, raid_id):
        conn = self.bot.conn
        channel_id, guild_id, name, tier, description, timestamp = select_one(conn, 'Raids', ['channel_id', 'guild_id', 'name', 'tier', 'boss', 'time'], ['raid_id'], [raid_id])
        res = select_one(conn, 'Settings', ['guild_events'], ['guild_id'], [guild_id])
        if not res:
            return

        metadata = {"location": f"https://discord.com/channels/{guild_id}/{channel_id}/{raid_id}"}
        start_time = datetime.utcfromtimestamp(timestamp).isoformat() + 'Z'
        end_time = datetime.utcfromtimestamp(timestamp+7200).isoformat() + 'Z'
        data = {
            "entity_metadata": metadata,
            'name': " ".join([name, tier]),
            "privacy_level": 2,
            "scheduled_start_time": start_time,
            "scheduled_end_time": end_time,
            "description": description,
            "entity_type": 3
            }
        url = self.bot.api + f"guilds/{guild_id}/scheduled-events"
        r = requests.post(url, headers=self.headers, json=data)
        r.raise_for_status()
        event = r.json()
        event_id = event['id']
        return event_id

    def modify_guild_event(self, raid_id):
        conn = self.bot.conn
        guild_id, event_id, name, tier, description, timestamp = select_one(conn, 'Raids', ['guild_id', 'event_id', 'name', 'tier', 'boss', 'time'], ['raid_id'], [raid_id])
        if not event_id:
            return

        start_time = datetime.utcfromtimestamp(timestamp).isoformat() + 'Z'
        end_time = datetime.utcfromtimestamp(timestamp+7200).isoformat() + 'Z'
        data = {
                'name': " ".join([name, tier]),
                'description': description,
                'scheduled_start_time': start_time,
                'scheduled_end_time': end_time
                }
        url = self.bot.api + f"guilds/{guild_id}/scheduled-events/{event_id}"
        r = requests.patch(url, headers=self.headers, json=data)
        r.raise_for_status()

    def delete_guild_event(self, raid_id):
        conn = self.bot.conn
        try:
            guild_id, event_id = select_one(conn, 'Raids', ['guild_id', 'event_id'], ['raid_id'], [raid_id])
        except TypeError:
            logger.info("Raid already deleted from database.")
            return
        if not event_id:
            return

        url = self.bot.api + f"guilds/{guild_id}/scheduled-events/{event_id}"
        r = requests.delete(url, headers=self.headers)
        r.raise_for_status()

    def get_events(self):
        current_time = datetime.now().timestamp()
        if self.cached_events_at and self.cached_events_at + 86400 > current_time:
            return self.upcoming_events

        s = requests.Session()
        s.mount("https://forums.lotro.com", ECDHEAdapter())
        r = s.get("https://forums.lotro.com/forums/showthread.php?646193-LOTRO-Events-Schedule&s=37ca62f1171274310d6709145d372d3f&p=7646830#post7646830")
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
        parsed_events = [(event[0], self.parse_event_time(event[1]), self.parse_event_time(event[2])) for event in events]

        cutoff_past = current_time - 86400
        cutoff_future = current_time + 90 * 86400
        upcoming_events = [event for event in parsed_events if cutoff_past < event[2] < cutoff_future]
        self.cached_events_at = current_time
        self.upcoming_events = upcoming_events
        return upcoming_events

    def events_embed(self, guild_id):
        events = self.get_events()

        title = _("Upcoming events:")
        embed = discord.Embed(title=title, colour=discord.Colour(0x3498db))
        for e in events:
            time_str = f"<t:{e[1]}> -- <t:{e[2]}>"
            embed.add_field(name=e[0], value=time_str, inline=False)
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = datetime.fromtimestamp(self.cached_events_at)
        return embed

    def parse_event_time(self, time):
        time = pytz.timezone("America/New_York").localize(dateparser.parse(time)).timestamp()
        return int(time)

    @app_commands.command(name=_("events"), description=_("Shows upcoming official LotRO events in your local time."))
    @app_commands.guild_only()
    async def events_respond(self, interaction: discord.Interaction):
        await interaction.response.send_message(_("Waiting for lotro.com to respond..."))
        events = self.events_embed(interaction.guild_id)
        await interaction.edit_original_message(content='', embed=events)

    group = CalendarGroup()

    @group.command(name=_("off"), description=("Turn off calendars."))
    async def calendar_off(self, interaction: discord.Interaction):
        if not self.is_raid_leader(interaction.user, interaction.guild):
            await interaction.response.send_message(_("You must be a raid leader to change the calendar settings."), ephemeral=True)
            return
        upsert(self.conn, 'Settings', ['calendar', 'guild_events'], [None, False], ['guild_id'], [interaction.guild_id])
        content = _("Events will not be posted to a calendar.")
        await interaction.response.send_message(content, ephemeral=True)
        self.conn.commit()

    @group.command(name=_("channel"), description=("Post events to calendar in this channel."))
    async def calendar_channel(self, interaction: discord.Interaction):
        if not self.is_raid_leader(interaction.user, interaction.guild):
            await interaction.response.send_message(_("You must be a raid leader to change the calendar settings."), ephemeral=True)
            return
        channel = interaction.channel
        guild = interaction.guild
        perms = channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.response.send_message(_("Missing permissions to access this channel."))
            return
        upsert(self.conn, 'Settings', ['guild_events'], [False], ['guild_id'], [guild.id])
        content = _("Events will be posted to this channel.")
        await interaction.response.send_message(content, ephemeral=True)
        # post calendar will commit
        await self.post_calendar(guild.id, channel)

    @group.command(name=_("discord"), description=("Post events to discord calendar."))
    async def calendar_discord(self, interaction: discord.Interaction):
        if not self.is_raid_leader(interaction.user, interaction.guild):
            await interaction.response.send_message(_("You must be a raid leader to change the calendar settings."), ephemeral=True)
            return
        upsert(self.conn, 'Settings', ['calendar', 'guild_events'], [None, True], ['guild_id'], [interaction.guild_id])
        content = _("Events will be posted as discord guild events.")
        await interaction.response.send_message(content, ephemeral=True)
        self.conn.commit()

    @group.command(name=_("both"), description=("Post events to both discord and channel calendar."))
    async def calendar_both(self, interaction: discord.Interaction):
        if not self.is_raid_leader(interaction.user, interaction.guild):
            await interaction.response.send_message(_("You must be a raid leader to change the calendar settings."), ephemeral=True)
            return
        channel = interaction.channel
        guild = interaction.guild
        perms = channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.response.send_message(_("Missing permissions to access this channel."))
            return
        upsert(self.conn, 'Settings', ['guild_events'], [True], ['guild_id'], [guild.id])
        content = _("Events will be posted to this channel and as discord guild events.")
        await interaction.response.send_message(content, ephemeral=True)
        # post calendar will commit
        await self.post_calendar(guild.id, channel)


async def setup(bot):
    await bot.add_cog(CalendarCog(bot))
    logger.info("Loaded Calendar Cog.")
