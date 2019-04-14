This is a discord bot aimed at making it easy to schedule raids in a discord server. It is developed for LotRO but could work for any game if you edit the class names in the config file.

When the `!raid` command is called the bot will create an embed specifying the raid time in server time, New York's, London's and Sydney's time. It will add class emojis to this embed for users to interact with. When a user clicks on a class emoji it will update the embed listing the user's name and available classes. Moreover it will add a boss emoji and a timer emoji that allows the raid leader to change these values.

In addition the bot will create a "role post" that allows users to sign up for class roles by interacting through class emojis. There is also an experimental apply feature that asks a user two standard questions.

Config file values:
BOT_TOKEN: Your discord's bot token (this is not the client secret).\
CLASSES: The classes in your game. Note your discord server must have custom emojis named exactly the same. Emojis for LotRO are included, you can upload these to your discord server.\
CHANNELS: The role post will be posted to the BOT channel. Any incoming applications will be posted to the APPLY channel, so this should be officer only.\
BOSS: Custom boss emoji used to update raid boss info on a raid post.\
LEADER: Name of the discord role that will be allowed to update bosses and times for raid post.\
SERVER_TZ: The raid time in the header of the embed will be posted in this timezone. (Requires TZ database name)\

An example config file has been included.

There are also two screenshots provided as example.

Please ensure the bot has the correct permissions: 268512336.

(Manage roles, manage channels, read messages, read message history, send messages, manage messages, add reactions.)
