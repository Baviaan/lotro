class Player(object):
    def __init__(self, user):
        self.id = user.id
        self.name = user.name
        self.display_name = user.display_name
        self.classes = set()

    def __eq__(self, other):
        """Overrides the default implementation"""
        if isinstance(other, Player):
            return self.id == other.id
        return False

    def __hash__(self):
        return hash(self.id)

    def id(self):
        return self.id

    def name(self):
        return self.name

    def display_name(self):
        return self.display_name

    def classes(self):
        return self.classes

    def add_classes(self, emoji):
        player_class = PlayerClass(emoji)
        self.classes.add(player_class)

    def __str__(self):
        classes_string = ""
        for emoji in self.classes:
            classes_string = classes_string + emoji.name + ", "
        classes_string = classes_string[:-2] + "."
        return "{0} on {1}".format(self.display_name, classes_string)


class PlayerClass(object):
    def __init__(self, discord_emoji):
        self.name = discord_emoji.name
        self.emoji = str(discord_emoji)

    def __eq__(self, other):
        """Overrides the default implementation"""
        if isinstance(other, PlayerClass):
            return self.emoji == other.emoji
        return False

    def __hash__(self):
        return hash(self.emoji)

    def name(self):
        return self.name

    def emoji(self):
        return self.emoji

    def __str__(self):
        return self.emoji
