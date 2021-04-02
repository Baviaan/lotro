from datetime import datetime
import discord
from discord.ext import commands
import gettext
import json
import locale
import logging
import re

from database import create_connection, create_table, select, upsert


class Bot(commands.Bot):

    def __init__(self):
        self.launch_time = datetime.utcnow()

        version = ""
        with open('__init__.py') as f:
            regex = r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]'
            version = re.search(regex, f.read(), re.MULTILINE).group(1)
        self.version = version

        with open('config.json', 'r') as f:
            config = json.load(f)
        self.token = config['BOT_TOKEN']
        self.server_tz = config['SERVER_TZ']
        self.display_times = config['TIMEZONES']
        self.default_prefix = config['PREFIX']
        role_names = config['CLASSES']
        self.role_names = tuple(role_names)

        # Get id for discord server hosting custom emoji.
        try:
            self.host_id = int(config['HOST'])
        except KeyError:
            self.host_id = None

        logfile = 'raid_bot.log'
        logging.basicConfig(filename=logfile, level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        self.logger = logger

        self.logger.info("Running version " + self.version)

        language = config['LANGUAGE']
        if language == 'fr':
            locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
        localization = gettext.translation('messages', localedir='locale', languages=[language], fallback=True)
        if language == 'en' or hasattr(localization, '_catalog'):  # Technically 'en' has no file.
            logger.info("Using language file for '{0}'.".format(language))
        else:
            logger.warning("Language file '{0}' not found. Defaulting to English.".format(language))
        localization.install()

        conn = create_connection('raid_db')
        if conn:
            self.logger.info("Bot connected to raid database.")
            create_table(conn, 'settings')
            results = select(conn, 'Settings', ['guild_id', 'prefix'])
            self.prefixes = dict(results)
        else:
            self.prefixes = {}
            self.logger.error("main could not create database connection!")
        self.conn = conn

        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.reactions = True

        super().__init__(command_prefix=self.prefix_manager, case_insensitive=True, intents=intents,
                         activity=discord.Game(name=self.version))

        def globally_block_dms(ctx):
            if ctx.guild is None:
                raise commands.NoPrivateMessage("No dm allowed!")
            else:
                return True

        super().add_check(globally_block_dms)

    def prefix_manager(self, bot, message):
        """Returns a guild specific prefix if it has been set. Default prefix otherwise."""
        try:
            guild_id = message.guild.id
        except AttributeError:  # If the command is used in dm there is no guild attribute
            prefix = self.default_prefix
        else:
            prefix = self.prefixes.get(guild_id, self.default_prefix)
            if not prefix:
                prefix = self.default_prefix
        return commands.when_mentioned_or(prefix)(bot, message)

    async def on_ready(self):
        self.logger.info("We have logged in as {0}.".format(self.user))
        if not self.guilds:
            self.logger.error("The bot is not in any guilds. Shutting down.")
            await self.close()
            return
        for guild in self.guilds:
            self.logger.info('Welcome to {0}.'.format(guild))
        try:
            self.load_extension('config_cog')
            self.load_extension('dev_cog')
            self.load_extension('role_cog')
            self.load_extension('time_cog')
            # Load after time cog
            self.load_extension('calendar_cog')
            self.load_extension('raid_cog')
            # Load slash cog
            self.load_extension('slash_cog')
            self.load_extension('register_cog')
            # Load custom cog
            self.load_extension('custom_cog')
        except commands.ExtensionAlreadyLoaded:
            pass

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(_("Please use this command in a server."))
        else:
            await ctx.send(error, delete_after=10)
            if not isinstance(error, commands.CommandNotFound):
                self.logger.warning("Error for command: " + ctx.message.content)
                self.logger.warning(error)

    async def on_command_completion(self, ctx):
        timestamp = int(datetime.utcnow().timestamp())
        res = upsert(self.conn, 'Settings', ['last_command'], [timestamp], ['guild_id'], [ctx.guild.id])
        if res:
            self.conn.commit()
