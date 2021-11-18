import datetime
import discord
from discord.ext import commands
import logging
import pytz
import requests

from database import increment, select_one, select_order, upsert
from time_cog import Time

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SlashCog(commands.Cog):
    api = "https://discord.com/api/v8/"

    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        self.host_id = bot.host_id
        bot.add_listener(self.on_interaction)
        self.raid_cog = bot.get_cog('RaidCog')
        self.config_cog = bot.get_cog('ConfigCog')
        self.calendar_cog = bot.get_cog('CalendarCog')
        self.time_cog = bot.get_cog('TimeCog')

    async def on_interaction(self, interaction):
        if interaction.type != discord.InteractionType.application_command:
            return
        guild_id = interaction.guild_id
        if not guild_id:
            self.interaction_response(interaction, _("Use this command in a server."))
            return
        user = interaction.user
        d = interaction.data
        name = d['name']
        try:
            if d['options'][0]['type'] == 1:
                name = "_".join([name, d['options'][0]['name']])
                options = {option['name']: option['value'] for option in d['options'][0]['options']}
            else:
                options = {option['name']: option['value'] for option in d['options']}
        except KeyError:
            options = None
        ephemeral = True
        embed = None

        post_new_raid = False
        post_new_calendar = False
        update_roles = False
        post_events = False
        guild = self.bot.get_guild(guild_id)
        channel_required_commands = self.raid_cog.nicknames[:]
        channel_required_commands.extend(['custom', 'calendar', 'twitter_on', 'twitter_off'])
        if name in channel_required_commands:
            channel = interaction.channel
            perms = channel.permissions_for(guild.me)
            if not (perms.send_messages and perms.embed_links):
                 channel = None

        if name in self.raid_cog.nicknames or name == 'custom':
            if not channel:
                content = _("Missing permissions to access this channel.")
            else:
                time_arg = options['time']
                try:
                    timestamp = Time().converter(self.bot, guild_id, user.id, time_arg)
                except commands.BadArgument as e:
                    content = str(e)
                else:
                    content = _("Posting a new raid!")
                    post_new_raid = True
        elif name == 'calendar':
            if not channel:
                content = _("Missing permissions to access this channel.")
            else:
                if self.is_raid_leader(user, guild_id):
                    content = _("The calendar will be updated in this channel.")
                    post_new_calendar = True
                else:
                    content = _("You must be a raid leader to set the calendar.")
        elif name.startswith('twitter'):
            if user.guild_permissions.administrator:
                channel_id = None
                if name == 'twitter_on':
                    try:
                        channel_id = channel.id
                    except AttributeError:
                        content = _("Missing permissions to access this channel.")
                    else:
                        content = _("@lotro tweets will be posted to this channel.")
                elif name == 'twitter_off':
                    content = _("Tweets will no longer be posted to this channel.")
                else:
                    return
                res = upsert(self.conn, 'Settings', ['twitter'], [channel_id], ['guild_id'], [guild_id])
            else:
                content = _("You must be an admin to set up tweets.")
        elif name == 'events':
            ephemeral = False
            content = _("Waiting for lotro.com to respond...")
            post_events = True
        elif name == 'leader':
            ephemeral = False
            content = self.parse_leader_slash_command(guild_id, user, options)
        elif name == 'remove_roles':
            content = _("Removing your class roles...")
            update_roles = True
        elif name == 'time_zones_personal':
            content = self.process_time_zones_personal(user.id, options)
        elif name == 'time_zones_server':
            ephemeral = False
            content = self.process_time_zones_server(user, guild_id, options)
        elif name == 'about':
            ephemeral = False
            embed = await self.config_cog.about_embed()
            embed = embed.to_dict()
            content = ''
        elif name == 'privacy':
            ephemeral = False
            content = _("**PII:**\n"
                        "When you sign up for a raid the bot stores the time, your discord id, discord nickname and the class("
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
                        "Use `/time_zones` to change the default time settings and "
                        "you can designate a raid leader role with `/leader`, which allows non-admins to edit raids."
                        ).format(guild.name)
        elif name == 'server_time':
            content = self.process_server_time(guild_id)
        elif name == 'list_players':
            ephemeral = False
            player_msg, success = self.process_list_players(user, guild_id, options)
            if success:
                embed = player_msg.to_dict()
                content = ''
            else:
                content = player_msg  # string
        elif name == 'kin':
            content = self.parse_priority_slash_command(guild_id, user, options)
        else:
            content = _("Slash command not yet supported.")

        self.interaction_response(interaction, content, ephemeral=ephemeral, embed=embed)

        if post_new_raid:
            await self.raid_command(name, guild_id, channel, user.id, timestamp, options)
        elif post_new_calendar:
            await self.post_calendar(guild_id, channel)
        elif update_roles:
            await self.process_roles_command(guild, user, interaction.token)
        elif post_events:
            self.process_events_command(guild_id, interaction.token)

        timestamp = int(datetime.datetime.now().timestamp())
        upsert(self.conn, 'Settings', ['last_command'], [timestamp], ['guild_id'], [guild_id])
        increment(self.conn, 'Settings', 'slash_count', ['guild_id'], [guild_id])
        self.conn.commit()

    def interaction_response(self, interaction, content, ephemeral=False, embed=None):
        json = {
            'type': 4,
            'data': {
                'content': content
            }
        }
        if ephemeral:
            json['data']['flags'] = 64
        if embed:
            json['data']['embeds'] = [embed]

        url = self.api + "interactions/{0}/{1}/callback".format(interaction.id, interaction.token)
        r = requests.post(url, json=json)

    def is_raid_leader(self, user, guild_id):
        if user.guild_permissions.administrator:
            return True
        raid_leader_id = select_one(self.conn, 'Settings', ['raid_leader'], ['guild_id'], [guild_id])
        if raid_leader_id:
            guild = self.bot.get_guild(guild_id)
            raid_leader = guild.get_role(raid_leader_id)
            if raid_leader in user.roles:
                return True
        return False

    async def process_roles_command(self, guild, member, token):
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

    def process_events_command(self, guild_id, token):
        embed = self.calendar_cog.events_embed(guild_id)
        embed = embed.to_dict()
        endpoint = self.api + "webhooks/{0}/{1}/messages/@original".format(self.bot.user.id, token)
        json = {
            'content': '',
            'embeds': [embed]
        }
        requests.patch(endpoint, json=json)


    def parse_leader_slash_command(self, guild_id, user, options):
        if not user.guild_permissions.administrator:
            content = _("You must be an admin to change the raid leader role.")
            return content
        leader_id = options['role']
        res = upsert(self.conn, 'Settings', ['raid_leader'], [leader_id], ['guild_id'], [guild_id])
        self.conn.commit()
        content = _("Successfully updated the raid leader role!")
        return content

    async def raid_command(self, name, guild_id, channel, user_id, time, options):
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
        await self.raid_cog.post_raid(name, tier, boss, time, roster, guild_id, channel, user_id)

    def process_time_zones_personal(self, user_id, options):
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
            res = upsert(conn, 'Timezone', ['timezone'], [tz], ['player_id'], [user_id])
            if res:
                conn.commit()
                content = _("Set default time zone to {0}.").format(tz)
            else:
                content = _("An error occurred.")
        return content

    def process_time_zones_server(self, user, guild_id, options):
        if not self.is_raid_leader(user, guild_id):
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

    def process_server_time(self, guild_id):
        tz_str = self.time_cog.get_server_timezone(guild_id)
        server_tz = pytz.timezone(tz_str)
        server_time = datetime.datetime.now(tz=server_tz)

        formatted_time = server_time.strftime("%A %H:%M")
        content = _("Current server time: {0}").format(formatted_time)
        return content

    def process_list_players(self, user, guild_id, options):
        if not self.is_raid_leader(user, guild_id):
            return _("You must be a raid leader to list players."), False
        raid_number = 1
        cutoff = 24
        if options:
            try:
                raid_number = options['raid_number']
            except KeyError:
                pass
            try:
                cutoff = options['cut-off']
            except KeyError:
                pass
        conn = self.conn
        raids = select_order(conn, 'Raids', ['raid_id', 'name', 'time'], 'time', ['guild_id'], [guild_id])
        if raid_number > len(raids):
            return _("Cannot list raid {0}: only {1} raids exist.").format(raid_number, len(raids)), False
        elif raid_number < 1:
            return _("Please provide a positive integer."), False
        raid_id, raid_name, raid_time = raids[raid_number-1]
        player_data = select_order(conn, 'Players', ['byname', 'timestamp'], 'timestamp', ['raid_id', 'unavailable'], [raid_id, False])

        cutoff_time = raid_time - 3600 * cutoff
        embed_title = _("**Sign up list for {0} on <t:{1}>**").format(raid_name, raid_time)
        embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db))
        players_on = ["\u200b"]
        players_off = ["\u200b"]
        times_on = ["\u200b"]
        times_off = ["\u200b"]
        for row in player_data:
            if row[1]:
                time = row[1]
                if time < cutoff_time:
                    players_on.append(row[0])
                    times_on.append(f"<t:{time}:R>")
                else:
                    players_off.append(row[0])
                    times_off.append(f"<t:{time}:R>")
            else:
                players_on.append(row[0])
                times_on.append("\u200b")
        players_on = "\n".join(players_on)
        players_off = "\n".join(players_off)
        times_on = "\n".join(times_on)
        times_off = "\n".join(times_off)
        embed.add_field(name=_("Players:"), value=players_on)
        embed.add_field(name=_("Sign up time:"), value=times_on)
        embed.add_field(name="\u200b", value="\u200b")
        embed.add_field(name=_("Late players:"), value=players_off)
        embed.add_field(name=_("Sign up time:"), value=times_off)
        embed.add_field(name="\u200b", value="\u200b")
        return embed, True

    def parse_priority_slash_command(self, guild_id, user, options):
        if not user.guild_permissions.administrator:
            content = _("You must be an admin to change the kin role.")
            return content
        if not options:
            res = upsert(self.conn, 'Settings', ['priority'], [None], ['guild_id'], [guild_id])
            content = _("Kin role removed.")
            return content
        priority_id = options['role']
        res = upsert(self.conn, 'Settings', ['priority'], [priority_id], ['guild_id'], [guild_id])
        self.conn.commit()
        content = _("Successfully updated the kin role!")
        return content

def setup(bot):
    bot.add_cog(SlashCog(bot))
    logger.info("Loaded Slash Cog.")
