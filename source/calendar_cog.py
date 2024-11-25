import dateparser
import discord
import logging
import pytz
import re
import requests

from datetime import datetime, timedelta, timezone
from discord import app_commands
from discord.ext import commands

from database import select_one, select_order, upsert
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

    async def update_calendar(self, guild_id):
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

    def calendar_embed(self, guild_id):
        conn = self.bot.conn
        raids = select_order(conn, 'Raids', ['channel_id', 'raid_id', 'name', 'tier', 'time'], 'time', ['guild_id'],
                             [guild_id])

        title = _("Scheduled runs:")
        desc = _("Click the link to sign up!")
        embed = discord.Embed(title=title, description=desc, colour=discord.Colour(0x3498db))
        for raid in raids[:20]:
            timestamp = int(raid[4])
            tier = raid[3]
            if tier:
                msg = "[{name} {tier}](<https://discord.com/channels/{guild}/{channel}/{msg}>)\n".format(
                guild=guild_id, channel=raid[0], msg=raid[1], name=raid[2], tier=raid[3])
            else:
                msg = "[{name}](<https://discord.com/channels/{guild}/{channel}/{msg}>)\n".format(
                guild=guild_id, channel=raid[0], msg=raid[1], name=raid[2])
            embed.add_field(name=f"<t:{timestamp}:F>", value=msg, inline=False)
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = datetime.now()
        return embed

    async def create_guild_event(self, guild, raid_id):
        conn = self.bot.conn
        res = select_one(conn, 'Settings', ['guild_events'], ['guild_id'], [guild.id])
        if not res:
            return 0
        channel_id, name, tier, description, timestamp = select_one(conn, 'Raids', ['channel_id', 'name', 'tier', 'boss', 'time'], ['raid_id'], [raid_id])

        location = f"https://discord.com/channels/{guild.id}/{channel_id}/{raid_id}"
        start_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        end_time = datetime.fromtimestamp(timestamp+7200, tz=timezone.utc)
        if tier:
            event_name = " ".join([name, tier])
        else:
            event_name = name

        try:
            event = await guild.create_scheduled_event(name=event_name, start_time=start_time, end_time=end_time, entity_type=discord.EntityType.external, privacy_level=discord.PrivacyLevel.guild_only, location=location, description=description)
        except discord.Forbidden:
            logger.warning("Missing manage events permission for guild {0}".format(guild.id))
            event_id = None
        else:
            event_id = event.id
        return event_id

    async def modify_guild_event(self, guild, raid_id):
        conn = self.bot.conn
        res = select_one(conn, 'Settings', ['guild_events'], ['guild_id'], [guild.id])
        if not res:
            return
        event_id, name, tier, description, timestamp = select_one(conn, 'Raids', ['event_id', 'name', 'tier', 'boss', 'time'], ['raid_id'], [raid_id])
        if not event_id:
            return

        # discord.py does not have partial event
        event = await guild.fetch_scheduled_event(event_id, with_counts=False)
        start_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        end_time = datetime.fromtimestamp(timestamp+7200, tz=timezone.utc)
        if tier:
            event_name = " ".join([name, tier])
        else:
            event_name = name
        try:
            await event.edit(name=event_name, description=description, start_time=start_time, end_time=end_time)
        except discord.Forbidden:
            logger.warning("Missing manage events permission for guild {0}".format(guild.id))

    async def delete_guild_event(self, guild, raid_id):
        conn = self.bot.conn
        event_id = select_one(conn, 'Raids', ['event_id'], ['raid_id'], [raid_id])
        if not event_id:
            return

        # discord.py does not have partial event
        event = await guild.fetch_scheduled_event(event_id, with_counts=False)
        try:
            await event.delete()
        except discord.Forbidden:
            logger.warning("Missing manage events permission for guild {0}".format(guild.id))

    def get_events(self):
        current_time = datetime.now().timestamp()
        if self.cached_events_at and self.cached_events_at + 86400 > current_time:
            return self.upcoming_events

        r = requests.get("https://www.lotro.com/news/lotro-public-event-schedule-en")
        if not r.ok:
            logger.warning("Could not connect to lotro.com")
            return self.upcoming_events

        stripped = re.sub('<[^<]+?>', '', r.text)
        stripped = stripped.replace('\xa0', '')
        # Let us hope this questionable pattern is stable enough
        pattern = r'End Time/Date \(Eastern\)(.*)End Time/Date \(Eastern\)(.*)Share On:'

        prog = re.compile(pattern, flags=re.DOTALL)
        result = prog.search(stripped)
        events_data = result.group(2).strip().splitlines() + ['']
        events = [chunk for chunk in chunks(events_data, 5)]
        parsed_events = [(event[0], self.parse_event_time(event[1]), self.parse_event_time(event[2])) for event in events]

        cutoff_unlock = current_time - 30 * 86400
        cutoff_past = current_time - 86400
        cutoff_future = current_time + 60 * 86400

        upcoming_events = []
        for event in parsed_events:
            start_time = current_time
            if event[1]:
                start_time = event[1]
            if event[2]:
                if cutoff_past < event[2] and start_time < cutoff_future:
                    upcoming_events.append(event)
            else:
                if cutoff_unlock < start_time < cutoff_future:
                    upcoming_events.append(event)
            if start_time > cutoff_future:
                break

        self.cached_events_at = current_time
        self.upcoming_events = upcoming_events
        return upcoming_events

    def events_embed(self, guild_id):
        events = self.get_events()

        title = _("Upcoming events:")
        embed = discord.Embed(title=title, colour=discord.Colour(0x3498db))
        for e in events:
            time_str = ""
            if e[1] and e[2]:
                time_str = f"<t:{e[1]}> -- <t:{e[2]}>"
            else:
                if e[1]:
                    time_str = f"From <t:{e[1]}>"
                if e[2]:
                    time_str = f"At <t:{e[2]}>"
            embed.add_field(name=e[0], value=time_str, inline=False)
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = datetime.fromtimestamp(self.cached_events_at)
        return embed

    def parse_event_time(self, time_string):
        if not time_string:
            return None
        time_string = time_string.casefold()
        time_string = time_string.replace(" eastern", "")
        time_string = time_string.replace("approximately ", "")
        time = dateparser.parse(time_string)
        try:
            time = pytz.timezone("America/New_York").localize(time).timestamp()
        except:
            logger.info(f"Calendar failed to parse: {time_string}")
            return None
        return int(time)

    @app_commands.command(name=_("events"), description=_("Shows upcoming official LotRO events in your local time."))
    @app_commands.guild_only()
    async def events_respond(self, interaction: discord.Interaction):
        await interaction.response.send_message(_("Waiting for lotro.com to respond..."))
        events = self.events_embed(interaction.guild_id)
        await interaction.edit_original_response(content='', embed=events)

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
