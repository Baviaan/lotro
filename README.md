## Introduction
This is a discord bot aimed at making it easy to schedule raids in a discord server. It is developed for LotRO but could work for any game if you edit the class names in the config file.

When a raid command is called the bot will create an embed specifying the raid time formatted in the local time for everyone looking at it.
The bot will add class buttons to this embed for users to interact with.
When a user clicks on a class button it will update the embed, listing the user's discord nickname and available classes.
Moreover it will add tools, pickaxe, check mark and cross mark buttons.
A user can sign up with all his (previously used) classes by clicking the green check mark and cancel his sign up by clicking the red cross mark.
One can reset the classes for the green check mark sign up via the `/remove_roles` command.
The tools emoji can only be used by raid leaders to update the raid description, name, tier and time.
The pickaxe emoji can be used by raid leaders to pick people for the raid from available sign ups.

![Screenshot](./screenshots/raid.png)

If you would like to use the public bot please join our
[discord server](https://discord.gg/5YqSzuV)
to find the bot invite link.

If you would like to host your own instance, consult the self-hosting section below.

## Terms of Service
Effective: 27 May 2022

Last Updated: 27 April 2022

**By interacting with the application and using this service, you accept and agree to be bound by the terms and provisions of this agreement.**

We also have a Privacy Policy that applies to your use of our service and is incorporated into these terms.

The service is provided for free and may be terminated without notice.
Use of the service is at your own risk and we will not be responsible for any inconvenience caused by malfunction, outage or termination of the service.

You agree not to misuse or abuse the service.
Examples include, but are not limited to, spamming the service with interactions or submitting interactions containing inappropriate or offensive language.
We reserve the right to restrict your access to the service, without cause or notice, at our sole discretion.

We reserve the right to modify these conditions as we see fit and your continued usage of the service will signify your acceptance of any adjustments to these terms and provisions.
Any changes in your favour will take effect immediately and any other changes will take effect 30 days after publishing the updated Terms of Service.
For your convenience, a notification of changes will be posted to the application's official support server on Discord.

## Privacy Policy
Effective: 20 December 2022

Last Updated: 20 November 2022

This Privacy Policy explains how we collect, use, store, protect, and share your personal information through our services.

We care about privacy and try to limit the data we collect as much as possible.
Some information is required for core functionality and some information is optional for your convenience.
We describe our data collection more in detail below.
We do not sell your data.

**Data collection**

When you sign up for an event the service stores the time, your discord id, discord nickname and the class(es) you sign up with.
This data is collected to provide the core functionality of the service and is automatically deleted two hours after the scheduled event started, or immediately if you cancel your sign up for the event.

Optionally, you may submit your preferred time zone to the service, it will be stored alongside your discord id such that the service parses your commands in your preferred time zone without having to include the time zone for each command.
You can reset your time zone back to the default at any time using the same command.
If for any reason the service becomes permanently unavailable to users, we will delete all time zone data for you.

You can also store a specialization for your classes, this will be associated with your discord id.
While you can reset your specialization for a class, this does not delete your discord id from the database as there is one database row for all classes, thus your discord id may be used for another class as well.
There is currently no routine running to delete discord ids that have no specialization associated with them anymore for any class.
Please reach out to us in our official support server to have this data deleted.

**Data Protection**

All data submitted to us is transmitted via discord and thus should be considered public as it is not end to end encrypted.

**Data location**

Our servers are based in the U.S. and your data will be stored there.

**Exercising your rights**

You can delete data held about you yourself as described in the "Data collection" section.
If you encounter a problem, reach out to us in our official support server.

**Changes to this Privacy Policy**

We will update this Privacy Policy from time to time.
Any changes in your favour will take effect immediately and any other changes will take effect 30 days after publishing the updated Privacy Policy.
For your convenience, a notification of changes will be posted to the application's official support server on Discord.
If changes are significant we will provide a more prominent notice such as an announcement.


## Self-hosting

Prerequisites:\
python >= 3.8\
Check the requirements.txt file for required libraries.\
You can get all of them with: `python3 -m pip install -U -r requirements.txt`, assuming requirements.txt is in your current directory.

See details further below how to specify your configuration file and then simply run with `python3 main.py`

------------------------------------

You will need to make a copy of the 'example-config.json' file, name it 'config.json' and specify your configuration values.
(Windows might complain it doesn't know how to open json files, but simply select to open it with notepad and it'll work fine.)
See below for a guide how to create a discord bot.

Config file values:\
BOT_TOKEN: Your discord's bot token (this is not the client secret).\
CLASSES: The classes in your game. Note your discord server must have custom emojis named exactly the same. Emojis for LotRO are included, you can upload these to your discord server.\
LANGUAGE: The language of the bot. Currently only English "en" and French "fr" are supported.\
LINEUP: A sequence of zeroes and ones indicating for each slot whether the class should be present, in the order as specified under CLASSES. This will **ABSOLUTELY BREAK THE UI** if you specify too many ones. Please contain yourself.\
SERVER_TZ: The raid time in the header of the embed will be posted in this time zone. (Requires TZ database name.)\

See [es/messages.po](./source/locale/es/LC_MESSAGES/messages.po) if you wish to help translate to Spanish.
An example config file has been included for English and French.
**If language is not set to "en", the language binary file needs to be generated by running `msgfmt.py` using `messages.po` as input to create a file `messages.mo`.**

------------------------------------

See this link how to create a bot user on discord, obtain your bot token and invite the bot to your server:
https://discordpy.readthedocs.io/en/latest/discord.html#

Please ensure the bot has the correct permissions: 268453888.

(Manage roles, send messages, embed links.)

Please note the bot will automatically shut down if it is not in any discord servers.

------------------------------------

Any questions please ask in our discord server, invite code: `dGcBzPN`\
You can paste the code directly in the discord app when clicking the join server button.

------------------------------------

## Command overview

### Configuration commands
| Command | Requirement | Example | Notes |
| ------- |:-----------:| ------- | ----- |
| **/leader** \<role\>| Admin | /leader Officer | Specify "Raid Leader" role. Raid leaders can edit raids posted by others. |
| **/time_zones server** \<timezone\> | Admin | /time_zones server europe/paris | Set to US Eastern by default. This timezone is the default timezone for interpretation of raid commands. |
| **/kin** \<role\> | Admin | /kin Kin | Specify "kin" role. If specified kin members will be marked on the sign up sheet. |
| **/twitter on/off** | Admin | /twitter on | Post @lotro tweets to this channel. |

### Scheduling commands

| Command | Example | Notes |
| ------- | ------- | ----- |
| **/calendar channel** | /calendar channel | Provides an overview of all scheduled runs for the upcoming week, with direct links to the raid posts. This command will only have to be run once as the calendar will automatically populate with new runs. |
| **/calendar discord** | /calendar discord | Adds each run as guild scheduled event to discord's built-in calendar. |
| **/\<raid_name\>** \<tier\> \<time\> | /rem t2 tomorrow 8pm, /ad t3 friday 8pm | Fastest way to schedule a raid. |
| **/custom** \<name\> \<time\> \[tier\] | /custom my big event friday 8pm | Schedules a custom event. Tier argument is optional. |
| **/list_players** | /list_players | Lists the signed up players for a raid in order of sign up time. |

### User specific commands
| Command | Example | Notes |
| ------- | ------- | ----- |
| **/remove_roles** | /remove_roles | Removes the class roles you have. |
| **/time_zones personal** \<timezone\> | /time_zones personal europe/london | Set to server time by default. This timezone is used to interpret *your* raid commands. |

### Info commands

| Command | Notes |
| ------- | ----- |
| **/server_time** | Returns the current server time. |
| **/events** | Returns the upcoming official LotRO events. |
| **/about** | Shows some basic information about the bot. |

### Miscellaneous commands
| Command | Notes |
| ------- | ----- |
| **/privacy** | Displays information on data collection and retention. |
| **/welcome** | Resends the welcome message. |
