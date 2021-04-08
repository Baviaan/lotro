import datetime
import discord
from discord.ext import commands
import logging
import pytz
import requests

from database import increment, select_one, upsert
from time_cog import Time

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SlashCog(commands.Cog):
    api = "https://discord.com/api/v8/"

    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        self.host_id = bot.host_id
        bot.add_listener(self.on_socket_response)
        self.raid_cog = bot.get_cog('RaidCog')
        self.config_cog = bot.get_cog('ConfigCog')
        self.calendar_cog = bot.get_cog('CalendarCog')

    async def on_socket_response(self, msg):
        if msg['t'] != "INTERACTION_CREATE":
            return
        d = msg['d']
        token = d['token']
        name = d['data']['name']
        try:
            if d['data']['options'][0]['type'] == 1:
                name = d['data']['options'][0]['name']
                options = {option['name']: option['value'] for option in d['data']['options'][0]['options']}
            else:
                options = {option['name']: option['value'] for option in d['data']['options']}
        except KeyError:
            options = None
        guild_id = int(d['guild_id'])
        author_id = int(d['member']['user']['id'])
        author_perms = int(d['member']['permissions'])
        author_roles = [int(i) for i in d['member']['roles']]
        ephemeral = True
        embeds = False

        post_new_raid = False
        post_new_calendar = False
        update_roles = False
        post_events = False
        guild = self.bot.get_guild(guild_id)
        channel_required_commands = self.raid_cog.nicknames[:]
        channel_required_commands.extend(['custom', 'calendar'])
        if name in channel_required_commands:
            channel = self.bot.get_channel(d['channel_id'])
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(d['channel_id'])
                except discord.Forbidden:
                    channel = None
                else:
                    if not channel.permissions_for(guild.me).send_messages:
                        channel = None

        if name in self.raid_cog.nicknames or name == 'custom':
            if not channel:
                content = _("Missing permissions to access this channel.")
            else:
                time_arg = options['time']
                try:
                    time = await Time().converter(self.bot, guild_id, author_id, time_arg)
                except commands.BadArgument as e:
                    content = str(e)
                else:
                    content = _("Posting a new raid!")
                    post_new_raid = True
        elif name == 'calendar':
            if not channel:
                content = _("Missing permissions to access this channel.")
            else:
                allowed = self.is_raid_leader(author_perms, author_roles, guild_id)
                if allowed:
                    content = _("The calendar will be updated in this channel.")
                    post_new_calendar = True
                else:
                    content = _("You must be a raid leader to set the calendar.")
        elif name == 'events':
            ephemeral = False
            content = _("Waiting for lotro.com to respond...")
            post_events = True
        elif name == 'leader':
            ephemeral = False
            content = self.parse_leader_slash_command(guild_id, author_perms, options)
        elif name == 'remove_roles':
            content = _("Removing your class roles...")
            update_roles = True
        elif name == 'format':
            ephemeral = False
            fmt = options['format']
            res = upsert(self.conn, 'Settings', ['fmt_24hr'], [fmt], ['guild_id'], [guild_id])
            self.conn.commit()
            content = _("Successfully set this server's time format!")
        elif name == 'personal':
            content = self.process_time_zones_personal(author_id, options)
        elif name == 'server':
            ephemeral = False
            content = self.process_time_zones_server(author_perms, author_roles, guild_id, options)
        elif name == 'add_display':
            ephemeral = False
            content = self.process_time_zones_add_display(author_perms, author_roles, guild_id, options)
        elif name == 'reset_display':
            ephemeral = False
            content = self.process_time_zones_reset_display(author_perms, author_roles, guild_id)
        elif name == 'about':
            ephemeral = False
            embeds = True
            embed = await self.config_cog.about_embed()
            embed = embed.to_dict()
            content = ''
        elif name == 'privacy':
            ephemeral = False
            content = _("**PII:**\n"
                        "When you sign up for a raid the bot stores your discord id, discord nickname and the class("
                        "es) you sign up with. This information is automatically deleted 2 hours after the scheduled "
                        "raid time or immediately when you cancel your sign up.\n "
                        "If you set a default time zone for yourself, the bot will additionally store your time zone "
                        "along with your discord id such that it can parse times provided in your commands in your "
                        "preferred time zone.")
        elif name == 'welcome':
            ephemeral = False
            content = _("Greetings {0}! I am confined to Orthanc and here to spend my days doing your raid admin.\n\n"
                        "You can quickly schedule a raid with the `/rem` and `/ad` commands. Examples:\n"
                        "`/rem t2 Friday 8pm`\n"
                        "`/ad t3 26 July 1pm`\n"
                        "Use `/custom` to schedule a custom raid or meetup.\n\n"
                        "With `/calendar` you can get an (automatically updated) overview of all scheduled raids. "
                        "It is recommended you use a separate discord channel to display the calendar in.\n"
                        "Use `/time_zones` and `/format` to change the default time settings and "
                        "you can designate a raid leader role with `/leader`, which allows non-admins to edit raids."
                        ).format(guild.name)
        else:
            content = _("Slash command not yet supported.")

        json = {
            'type': 4,
            'data': {
                'content': content
            }
        }
        if ephemeral:
            json['data']['flags'] = 64
        if embeds:
            json['data']['embeds'] = [embed]

        url = self.api + "interactions/{0}/{1}/callback".format(d['id'], token)
        r = requests.post(url, json=json)

        if post_new_raid:
            await self.post_raid(name, guild_id, channel, author_id, time, options)
        elif post_new_calendar:
            await self.post_calendar(guild_id, channel)
        elif update_roles:
            await self.process_roles_command(guild, author_id, token)
        elif post_events:
            self.process_events_command(author_id, guild_id, token)

        timestamp = int(datetime.datetime.utcnow().timestamp())
        increment(self.conn, 'Settings', 'slash_count', ['guild_id'], [guild_id])
        res = upsert(self.conn, 'Settings', ['last_command'], [timestamp], ['guild_id'], [guild_id])
        if res:
            self.conn.commit()

    def is_raid_leader(self, author_perms, author_roles, guild_id):
        admin_permission = 0x00000008
        if (author_perms & admin_permission) == admin_permission:
            return True
        raid_leader_id = select_one(self.conn, 'Settings', ['raid_leader'], ['guild_id'], [guild_id])
        if raid_leader_id in author_roles:
            return True
        return False

    async def process_roles_command(self, guild, author_id, token):
        member = guild.get_member(author_id)
        if not member:
            member = await guild.fetch_member(author_id)

        try:
            await member.remove_roles(*[role for role in member.roles if role.name in self.bot.role_names])
            content = _("Successfully removed your class roles.")
        except discord.Forbidden:
            content = _("Missing permissions to manage the class roles!")
        endpoint = self.api + "webhooks/{0}/{1}/messages/@original".format(self.bot.user.id, token)
        json = {
            'content': content
        }
        requests.patch(endpoint, json=json)

    async def post_calendar(self, guild_id, channel):
        embed = self.calendar_cog.calendar_embed(guild_id)
        msg = await channel.send(embed=embed)
        ids = "{0}/{1}".format(channel.id, msg.id)
        res = upsert(self.conn, 'Settings', ['calendar'], [ids], ['guild_id'], [guild_id])
        self.conn.commit()

    def process_events_command(self, author_id, guild_id, token):
        embed = self.calendar_cog.events_embed(author_id, guild_id)
        embed = embed.to_dict()
        endpoint = self.api + "webhooks/{0}/{1}/messages/@original".format(self.bot.user.id, token)
        json = {
            'content': '',
            'embeds': [embed]
        }
        requests.patch(endpoint, json=json)


    def parse_leader_slash_command(self, guild_id, author_perms, options):
        admin_permission = 0x00000008
        if not (author_perms & admin_permission) == admin_permission:
            content = _("You must be an admin to change the raid leader role.")
            return content
        leader_id = options['role']
        res = upsert(self.conn, 'Settings', ['raid_leader'], [leader_id], ['guild_id'], [guild_id])
        self.conn.commit()
        content = _("Successfully updated the raid leader role!")
        return content

    async def post_raid(self, name, guild_id, channel, author_id, time, options):
        roster = False
        try:
            name = options['name']
        except KeyError:
            pass
        try:
            tier = options['tier']
        except KeyError:
            tier = ""
        else:
            if int(tier[1]) > 2:
                roster = True
        try:
            boss = options['aim']
        except KeyError:
            boss = ""
        full_name = self.raid_cog.get_raid_name(name)[0]
        # Check if time is in near future. Otherwise parsed date was likely unintended.
        current_time = datetime.datetime.utcnow()
        delta_time = datetime.timedelta(days=7)
        if current_time + delta_time < time:
            error_message = _("Please check the date <@{0}>. You are posting a raid for: {1} UTC.").format(author_id,
                                                                                                           time)
            await channel.send(error_message, delete_after=30)
        post = await channel.send('\u200B')
        raid_id = post.id
        timestamp = int(time.replace(tzinfo=datetime.timezone.utc).timestamp())  # Do not use local tz.
        raid_columns = ['channel_id', 'guild_id', 'organizer_id', 'name', 'tier', 'boss', 'time', 'roster']
        raid_values = [channel.id, guild_id, author_id, full_name, tier, boss, timestamp, roster]
        upsert(self.conn, 'Raids', raid_columns, raid_values, ['raid_id'], [raid_id])
        self.raid_cog.roster_init(raid_id)
        self.conn.commit()
        logger.info("Created new slash raid: {0} at {1}".format(full_name, time))
        embed = self.raid_cog.build_raid_message(guild_id, raid_id, "\u200B", None)
        await post.edit(embed=embed)
        await self.raid_cog.emoji_init(channel, post)
        self.raid_cog.raids.append(raid_id)
        await self.bot.get_cog('CalendarCog').update_calendar(guild_id)

    def process_time_zones_personal(self, author_id, options):
        conn = self.conn
        try:
            timezone = options['custom_timezone']
        except KeyError:
            timezone = options['timezone']
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError as e:
            content = _("{0} is not a valid time zone!").format(e)
        else:
            tz = str(tz)
            res = upsert(conn, 'Timezone', ['timezone'], [tz], ['player_id'], [author_id])
            if res:
                conn.commit()
                content = _("Set default time zone to {0}.").format(tz)
            else:
                content = _("An error occurred.")
        return content

    def process_time_zones_server(self, author_perms, author_roles, guild_id, options):
        if not self.is_raid_leader(author_perms, author_roles, guild_id):
            content = _("You must be a raid leader to change the server time zone.")
            return content
        conn = self.conn
        try:
            timezone = options['custom_timezone']
        except KeyError:
            timezone = options['timezone']
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError as e:
            content = _("{0} is not a valid time zone!").format(e)
        else:
            tz = str(tz)
            res = upsert(conn, 'Settings', ['server'], [tz], ['guild_id'], [guild_id])
            conn.commit()
            content = _("Set default time zone to {0}.").format(tz)
        return content

    def process_time_zones_add_display(self, author_perms, author_roles, guild_id, options):
        if not self.is_raid_leader(author_perms, author_roles, guild_id):
            content = _("You must be a raid leader to change the time zone display.")
            return content
        conn = self.conn
        try:
            timezone = options['custom_timezone']
        except KeyError:
            timezone = options['timezone']
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError as e:
            content = _("{0} is not a valid time zone!").format(e)
        else:
            tz = str(tz)
            tz_string = select_one(conn, 'Settings', ['display'], ['guild_id'], [guild_id])
            if tz_string:
                tz_string = ",".join([tz_string, tz])
            else:
                tz_string = tz
            res = upsert(conn, 'Settings', ['display'], [tz_string], ['guild_id'], [guild_id])
            conn.commit()
            content = _("Added {0} to be displayed.").format(tz)
        return content

    def process_time_zones_reset_display(self, author_perms, author_roles, guild_id):
        if not self.is_raid_leader(author_perms, author_roles, guild_id):
            content = _("You must be a raid leader to change the time zone display.")
            return content
        conn = self.conn
        res = upsert(conn, 'Settings', ['display'], [None], ['guild_id'], [guild_id])
        conn.commit()
        content = _("Reset time zone display to default.")
        return content


def setup(bot):
    bot.add_cog(SlashCog(bot))
    logger.info("Loaded Slash Cog.")
