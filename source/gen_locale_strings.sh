#!/bin/bash
./locale/pygettext.py bot.py calendar_cog.py config_cog.py dev_cog.py raid_cog.py register_cog.py role_cog.py slash_cog.py time_cog.py twitter_cog.py
mv messages.pot ./locale/
msgmerge --update locale/es/LC_MESSAGES/messages.po locale/messages.pot
msgmerge --update locale/fr/LC_MESSAGES/messages.po locale/messages.pot
