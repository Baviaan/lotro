import asyncio
from discord.ext import commands
import logging
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RegisterCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        self.guild_command_url = bot.api + "applications/{0}/guilds/{1}/commands".format(bot.user.id, bot.host_id)
        # self.command_url = self.guild_command_url
        self.command_url = bot.api + "applications/{0}/commands".format(bot.user.id)
        self.headers = {
            "Authorization": "Bot {0}".format(bot.token)
        }
        self.raid_cog = bot.get_cog('RaidCog')

    @staticmethod
    def parse_response(resp):
        if resp.status_code in [requests.codes.ok, requests.codes.created]:
            return True
        else:
            logger.info("Register response code: {0}".format(resp.status_code))
            logger.info("Response body:\n{0}".format(resp.text))
            return False

    def add_timezone_slash_commands(self):
        json = {
            "name": "time_zones",
            "description": _("Manage time zone options."),
            "options": self.format_timezone_subcommands()
        }
        
        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    @staticmethod
    def format_timezone_subcommands():
        timezone_options = [
                        {
                            "name": "timezone",
                            "description": _("Select a city representing your time zone."),
                            "type": 3,
                            "required": True,
                            "autocomplete": True
                        }
                    ]

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
            }
        ]
        return subcommands

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

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

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

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

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

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_roles_slash_command(self):
        json = {
            "name": 'remove_roles',
            "description": _("Deletes your class roles (used when signing up)."),
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_calendar_slash_command(self):
        json = {
            "name": 'calendar',
            "description": _("Post and update the calendar in this channel."),
            "options": [
                {
                    "name": "off",
                    "description": "Turn off calendars.",
                    "type": 1,
                },
                {
                    "name": "channel",
                    "description": "Post events to calendar in this channel.",
                    "type": 1,
                },
                {
                    "name": "discord",
                    "description": "Post events to discord calendar.",
                    "type": 1,
                },
                {
                    "name": "both",
                    "description": "Post events to both discord and channel calendar.",
                    "type": 1,
                }
            ]
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_events_slash_command(self):
        json = {
            "name": 'events',
            "description": _("Shows upcoming official LotRO events in your local time."),
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_twitter_slash_command(self):
        json = {
            "name": 'twitter',
            "description": _("Manage twitter settings."),
            "options": [
                {
                    "name": "on",
                    "description": "Turn on tweets in this channel.",
                    "type": 1,
                },
                {
                    "name": "off",
                    "description": "Turn off tweets in this channel.",
                    "type": 1,
                }
            ]
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_about_slash_command(self):
        json = {
            "name": 'about',
            "description": _("Show information about this bot."),
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_privacy_slash_command(self):
        json = {
            "name": 'privacy',
            "description": _("Show information on data collection."),
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_welcome_slash_command(self):
        json = {
            "name": 'welcome',
            "description": _("Resend the welcome message."),
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_server_time_slash_command(self):
        json = {
            "name": 'server_time',
            "description": _("Shows the current server time."),
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_list_players_slash_command(self):
        json = {
            "name": "list_players",
            "description": _("List the signed up players for a raid in order of sign up time."),
            "options": [
                {
                    "name": "raid_number",
                    "description": _("Specify the raid to list, e.g. 2 for the second upcoming raid. This defaults to 1 if omitted."),
                    "type": 4,
                    "required": False
                },
                {
                    "name": "cut-off",
                    "description": _("Specify cut-off time in hours before raid time. This defaults to 24 hours if omitted."),
                    "type": 4,
                    "required": False
                }
            ]
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    def add_priority_slash_command(self):
        json = {
            "name": 'kin',
            "description": _("Set your kin role to distinguish kin sign ups from non-kin."),
            "options": [
                {
                    "name": "role",
                    "description": "Discord role.",
                    "type": 8,
                    "required": False
                }
            ]
        }

        r = requests.post(self.command_url, headers=self.headers, json=json)
        return self.parse_response(r)

    @commands.command()
    @commands.is_owner()
    async def register(self, ctx, command):
        if command == 'raid':
            for key, name in self.raid_cog.raid_lookup.items():
                ok = self.add_raid_slash_command(key, name)
                if ok:
                    logger.info("Registered {0} slash command.".format(key))
                else:
                    logger.warning("Failed to register {0} slash command.".format(key))
                await asyncio.sleep(5)  # Avoid rate limits
        else:
            func_dict = {
                    'timezone': self.add_timezone_slash_commands,
                    'custom': self.add_custom_raid_slash_command,
                    'leader': self.add_leader_slash_command,
                    'roles': self.add_roles_slash_command,
                    'calendar': self.add_calendar_slash_command,
                    'events': self.add_events_slash_command,
                    'twitter': self.add_twitter_slash_command,
                    'about': self.add_about_slash_command,
                    'privacy': self.add_privacy_slash_command,
                    'welcome': self.add_welcome_slash_command,
                    'server_time': self.add_server_time_slash_command,
                    'list_players': self.add_list_players_slash_command,
                    'priority': self.add_priority_slash_command
                }
            try:
                ok = func_dict[command]()
            except KeyError:
                await ctx.send("Command not found.")
            else:
                if ok:
                    logger.info("Registered {0} slash command.".format(command))
                else:
                    logger.error("Failed to register {0} slash command.".format(command))


def setup(bot):
    bot.add_cog(RegisterCog(bot))
    logger.info("Loaded Register Cog.")
