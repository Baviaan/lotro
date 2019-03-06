import discord
import datetime
import dateparser

def usr_str2time(time_string):
    # Takes a user provided string as input and attempts to parse it to a time object.
    # Returns None if parse fails.
    if 'server' in time_string:
        #strip off server (time) and return as US Eastern time
        time_string = time_string.partition('server')[0]
        time = dateparser.parse(time_string, settings={'PREFER_DATES_FROM': 'future','TIMEZONE': 'US/Eastern', 'RETURN_AS_TIMEZONE_AWARE': True})
    else:
        time = dateparser.parse(time_string, settings={'PREFER_DATES_FROM': 'future','RETURN_AS_TIMEZONE_AWARE': True})
    # return time in UTC
    if time is not None:
        time = convert_local_time(time,True)
    return time

def build_raid_message(raid,text):
    # takes raid dictionary as input and prepares the embed using text for the text field.
    time_string = build_time_string(raid['TIME'])
    server_time = dateparser.parse(str(raid['TIME']), settings={'TIMEZONE': 'US/Eastern', 'RETURN_AS_TIMEZONE_AWARE': True})
    server_time = convert_local_time(server_time,False)
    header_time = server_time.strftime('%A %-I:%M %p server time')
    embed = discord.Embed(title='{0} T{1} at {2}'.format(raid['NAME'],raid['TIER'],header_time), colour = discord.Colour(0x3498db), description='Bosses: {0}'.format(raid['BOSS']))
    embed.add_field(name='Time zones:',value=time_string)
    embed.add_field(name='\u200b',value='\u200b')
    for i in range(len(text)):
        if i == 0:
            embed.add_field(name='The following {0} players are available:'.format(len(raid['AVAILABLE'])),value=text[i])
        else:
            embed.add_field(name='\u200b',value=text[i])
    embed.set_footer(text='{0}'.format(raid['TIME']))
    return embed

def build_raid_message_players(available):
    # Takes the available players dictionary as input and puts them in a string with their classes.
    # Initialise.
    if len(available) == 0:
        number_of_fields = 1
    else:
        number_of_fields = ((len(available)-1) // 6) + 1
    msg = []
    for i in range(number_of_fields):
        msg.append('')
    number_of_players = 0
    # Fill the fields.
    for user in available.values():
        index = number_of_players // 6
        number_of_players = number_of_players + 1
        msg[index] = msg[index] + user['DISPLAY_NAME'] + ' '
        for emoji in user['CLASSES']:
            msg[index] = msg[index] + str(emoji)
        msg[index] = msg[index] + '\n'
    if msg[0] == '':
        msg[0] = '\u200b'
    return msg

def build_time_string(time):
    new_york_time = dateparser.parse(str(time), settings={'TIMEZONE': 'US/Eastern', 'RETURN_AS_TIMEZONE_AWARE': True})
    new_york_time = convert_local_time(new_york_time,False)
    london_time = dateparser.parse(str(time), settings={'TIMEZONE': 'Europe/London', 'RETURN_AS_TIMEZONE_AWARE': True})
    london_time = convert_local_time(london_time,False)
    sydney_time = dateparser.parse(str(time), settings={'TIMEZONE': 'Australia/Sydney', 'RETURN_AS_TIMEZONE_AWARE': True})
    sydney_time = convert_local_time(sydney_time,False)
    time_string = 'New York: ' + new_york_time.strftime('%A %-I:%M %p') + '\n' + 'London: ' + london_time.strftime('%A %-I:%M %p') + '\n' + 'Sydney: ' + sydney_time.strftime('%A %-I:%M %p')
    return time_string

def convert_local_time(time,convert_utc):
    # Compute offset
    offset = time.utcoffset()
    # Strip time zone
    time = time.replace(tzinfo=None)
    if convert_utc:
        time = time - offset
    else:
        time = time + offset
    return time
