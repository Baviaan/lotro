from player import Player


class Raid(object):

    def __init__(self, name, tier, boss, time):
        self.name = name
        self.tier = tier
        self.boss = boss
        self.time = time
        self.players = set()
        self.post_id = None
        self.channel_id = None
        self.guild_id = None

    def name(self):
        return self.name

    def tier(self):
        return self.tier

    def boss(self):
        return self.boss

    def time(self):
        return self.time

    def set_time(self,time):
        self.time = time

    def set_boss(self,boss):
        self.boss = boss

    def players(self):
        return self.players

    def add_player(self,user,emoji):
        for player in self.players:
            if player.id == user.id:
                player.add_classes(emoji)
                return False
        player = Player(user)
        self.players.add(player)
        player.add_classes(emoji)
        return True

    def remove_player(self,user):
        for player in self.players:
            if player.id == user.id:
                self.players.remove(player)
                return True
        return False

    def post_id(self):
        return self.post_id

    def set_post_id(self,post_id):
        self.post_id = post_id

    def channel_id(self):
        return self.channel_id

    def set_channel_id(self,channel_id):
        self.channel_id = channel_id

    def guild_id(self):
        return self.guild_id

    def set_guild_id(self,guild_id):
        self.guild_id = guild_id

    def __str__(self):
        player_string = "the following players:\n"
        for player in self.players:
            player_string = player_string + str(player) + "\n"
        player_string = player_string[:-1]
        return "Guild {0}; {1} {2} at {3} with {4}".format(self.guild_id,self.name,self.tier,self.time,player_string)
