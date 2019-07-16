Prerequisites:\
python >= 3.6\
discord.py >= 1.0.0 (You can get the library with `python3 -m pip install -U discord.py`)\
dateparser >= 0.7.1 (`python3 -m pip install -U dateparser`)


------------------------------------

This is a discord bot aimed at making it easy to schedule raids in a discord server. It is developed for LotRO but could work for any game if you edit the class names in the config file.

When the `!raid` command is called the bot will create an embed specifying the raid time in server time, New York's, London's and Sydney's time. Server time is configurable. The bot will add class emojis to this embed for users to interact with. When a user clicks on a class emoji it will update the embed listing the user's nickname and available classes. Moreover it will add a boss emoji and a timer emoji that allows the raid leader to change these values. A user can sign up with all his classes by clicking the green check mark (not shown on screenshot) and cancel his sign up by clicking the red cross.

![Screenshot](./screenshots/raid.png)

In addition the bot will create a "role post" that allows users to sign up for mentionable class roles by interacting through class emojis. If you want to use the green check mark to sign up for raids you must sign up for your classes' roles. There is also an experimental apply feature that asks a user two standard questions.

![Screenshot](./screenshots/role.png)

For a detailed explanation how to use the bot's commands please use `!help` once it is running.

Config file values:\
BOT_TOKEN: Your discord's bot token (this is not the client secret).\
CLASSES: The classes in your game. Note your discord server must have custom emojis named exactly the same. Emojis for LotRO are included, you can upload these to your discord server.\
CHANNELS: The role post will be posted to the BOT channel. This channel will be purged so do NOT use a channel with info you want to keep. (In particular do not post your raids in the BOT channel.) Any incoming applications will be posted to the APPLY channel, so this should be officer only.\
BOSS: Custom boss emoji used to update raid boss info on a raid post.\
LEADER: Name of the discord role that will be allowed to update bosses and times for raid post.\
SERVER_TZ: The raid time in the header of the embed will be posted in this timezone. (Requires TZ database name)

An example config file has been included.

See this link how to create a bot user on discord, obtain your bot token and invite the bot to your server:
https://discordpy.readthedocs.io/en/latest/discord.html#

Please ensure the bot has the correct permissions: 268512336.

(Manage roles, manage channels, read messages, read message history, send messages, manage messages, add reactions.)

Any questions please ask in our discord server:
https://discord.gg/dGcBzPN
