import asyncio
from discord.ext import commands
import logging
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RegisterCog(commands.Cog):

    api = "https://discord.com/api/v8/"

    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        self.guild_command_url = self.api + "applications/{0}/guilds/{1}/commands".format(bot.user.id, bot.host_id)
        # self.command_url = self.guild_command_url
        self.command_url = self.api + "applications/{0}/commands".format(bot.user.id)
        self.raid_cog = bot.get_cog('RaidCog')

        with open('common_timezones.txt', 'r') as f:
            self.timezones = f.read().splitlines()

    def add_timezone_slash_commands(self):
        json = {
            "name": "time_zones",
            "description": _("Manage time zone options."),
            "options": self.format_timezone_subcommands()
        }
        
        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def format_timezone_subcommands(self):
        timezone_options = self.format_timezone_options()

        subcommands = [
            {
                "name": "personal",
                "description": _("Set your time zone to be used when interpreting your raid commands."),
                "type": 1,
                "options": timezone_options
            },
            {
                "name": "server",
                "description": _("Set server time for this discord server."),
                "type": 1,
                "options": timezone_options
            },
            {
                "name": "add_display",
                "description": _("Add a time zone to the displayed time zones."),
                "type": 1,
                "options": timezone_options
            },
            {
                "name": "reset_display",
                "description": _("Resets the displayed time zones to the default."),
                "type": 1,
            }
        ]
        return subcommands

    def format_timezone_options(self):
        timezone_choices = list(map(self.format_timezone_choice, self.timezones))
        timezone_options = [
                        {
                            "name": "timezone",
                            "description": _("Select a city representing your time zone."),
                            "type": 3,
                            "required": True,
                            "choices": timezone_choices
                        },
                        {
                            "name": "custom_timezone",
                            "description": _("Specify your time zone in the IANA tz database format. This will overwrite your previous choice."),
                            "type": 3
                        }
                    ]
        return timezone_options

    @staticmethod
    def format_timezone_choice(timezone):
        choice = {
            "name": "{0}".format(timezone),
            "value": "{0}".format(timezone)
        }
        return choice

    def add_raid_slash_command(self, key, name):
        json = {
            "name": key,
            "description": _("Schedule {0}.").format(name),
            "options": [
                {
                    "name": "tier",
                    "description": _("The raid tier."),
                    "type": 3,
                    "required": True,
                    "choices": self.format_tier_choices()
                },
                {
                    "name": "time",
                    "description": _("When the raid should be scheduled."),
                    "type": 3,
                    "required": True
                },
                {
                    "name": "aim",
                    "description": _("A short description of your objective."),
                    "type": 3,
                    "required": False
                }
            ]
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def add_custom_raid_slash_command(self):
        json = {
            "name": "custom",
            "description": _("Schedule a custom raid or meetup."),
            "options": [
                {
                    "name": "name",
                    "description": _("The name of the raid or meetup."),
                    "type": 3,
                    "required": True
                },
                {
                    "name": "time",
                    "description": _("When the raid should be scheduled."),
                    "type": 3,
                    "required": True
                },
                {
                    "name": "tier",
                    "description": _("The raid tier."),
                    "type": 3,
                    "required": False,
                    "choices": self.format_tier_choices()
                },
                {
                    "name": "aim",
                    "description": _("A short description of your objective."),
                    "type": 3,
                    "required": False
                }
            ]
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    @staticmethod
    def format_tier_choices():
        choices = [
                        {
                            "name": "1",
                            "value": "T1"
                        },
                        {
                            "name": "2",
                            "value": "T2"
                        },
                        {
                            "name": "2c",
                            "value": "T2c"
                        },
                        {
                            "name": "3",
                            "value": "T3"
                        },
                        {
                            "name": "4",
                            "value": "T4"
                        },
                        {
                            "name": "5",
                            "value": "T5"
                        }
                    ]
        return choices

    def add_leader_slash_command(self):
        json = {
            "name": 'leader',
            "description": _("Specify the role which is permitted to edit raids."),
            "options": [
                {
                    "name": "role",
                    "description": "Discord role.",
                    "type": 8,
                    "required": True
                }
            ]
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def add_roles_slash_command(self):
        json = {
            "name": 'remove_roles',
            "description": _("Deletes your class roles (used when signing up)."),
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def add_calendar_slash_command(self):
        json = {
            "name": 'calendar',
            "description": _("Post and update the calendar in this channel."),
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def add_format_slash_command(self):
        json = {
            "name": 'format',
            "description": _("Specify whether to use AM/PM or 24h time."),
            "options": [
                {
                    "name": "format",
                    "description": _("12h or 24h"),
                    "type": 5,
                    "required": True,
                    "choices": [
                        {
                            "name": "12h",
                            "value": False
                        },
                        {
                            "name": "24h",
                            "value": True
                        }
                    ]
                }
            ]
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def add_about_slash_command(self):
        json = {
            "name": 'about',
            "description": _("Show information about this bot."),
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def add_privacy_slash_command(self):
        json = {
            "name": 'privacy',
            "description": _("Show information on data collection."),
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    def add_welcome_slash_command(self):
        json = {
            "name": 'welcome',
            "description": _("Resend the welcome message."),
        }

        auth = "Bot " + self.bot.token
        headers = {
            "Authorization": auth
        }

        r = requests.post(self.command_url, headers=headers, json=json)

    @commands.command()
    @commands.is_owner()
    async def register(self, ctx):
        self.add_timezone_slash_commands()
        logger.info("Registered timezone slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        for key, name in self.raid_cog.raid_lookup.items():
            self.add_raid_slash_command(key, name)
            logger.info("Registered {0} slash command.".format(key))
            await asyncio.sleep(5)  # Avoid rate limits
        self.add_custom_raid_slash_command()
        logger.info("Registered custom raid slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        self.add_leader_slash_command()
        logger.info("Registered leader slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        self.add_roles_slash_command()
        logger.info("Registered roles slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        self.add_calendar_slash_command()
        logger.info("Registered calendar slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        self.add_format_slash_command()
        logger.info("Registered format slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        self.add_about_slash_command()
        logger.info("Registered about slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        self.add_privacy_slash_command()
        logger.info("Registered privacy slash command.")
        await asyncio.sleep(5)  # Avoid rate limits
        self.add_welcome_slash_command()
        logger.info("Registered welcome slash command.")
        await asyncio.sleep(5)  # Avoid rate limits


def setup(bot):
    bot.add_cog(RegisterCog(bot))
    logger.info("Loaded Register Cog.")
