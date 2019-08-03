from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from fuzzywuzzy import utils

def alphabet_emojis():
    alphabet = []
    alphabet.append("\U0001F1E6")
    alphabet.append("\U0001F1E7")
    alphabet.append("\U0001F1E8")
    alphabet.append("\U0001F1E9")
    alphabet.append("\U0001F1EA")
    alphabet.append("\U0001F1EB")
    alphabet.append("\U0001F1EC")
    alphabet.append("\U0001F1ED")
    alphabet.append("\U0001F1EE")
    alphabet.append("\U0001F1EF")
    alphabet.append("\U0001F1F0")
    alphabet.append("\U0001F1F1")
    alphabet.append("\U0001F1F2")
    alphabet.append("\U0001F1F3")
    alphabet.append("\U0001F1F4")
    alphabet.append("\U0001F1F5")
    alphabet.append("\U0001F1F6")
    alphabet.append("\U0001F1F7")
    alphabet.append("\U0001F1F8")
    alphabet.append("\U0001F1F9")
    alphabet.append("\U0001F1FA")
    alphabet.append("\U0001F1FB")
    alphabet.append("\U0001F1FC")
    alphabet.append("\U0001F1FD")
    alphabet.append("\U0001F1FE")
    alphabet.append("\U0001F1FF")
    return alphabet

def fp_ratio(s1, s2, force_ascii=True, full_process=True):
    """
    Return a measure of the sequences' similarity between 0 and 100, using fuzz.ratio and fuzz.partial_ratio.
    """
    if full_process:
        p1 = utils.full_process(s1, force_ascii=force_ascii)
        p2 = utils.full_process(s2, force_ascii=force_ascii)
    else:
        p1 = s1
        p2 = s2

    if not utils.validate_string(p1):
        return 0
    if not utils.validate_string(p2):
        return 0

    # should we look at partials?
    try_partial = True
    partial_scale = .9

    base = fuzz.ratio(p1, p2)
    len_ratio = float(max(len(p1), len(p2))) / min(len(p1), len(p2))

    # if strings are similar length, don't use partials
    if len_ratio < 1.5:
        try_partial = False

    if try_partial:
        partial = fuzz.partial_ratio(p1, p2) * partial_scale
        return utils.intr(max(base, partial))
    else:
        return utils.intr(base)


def get_match(word: str, word_list: list, score_cutoff: int = 80):
    """Uses fuzzywuzzy to see if word is close to entries in word_list

    Returns a tuple of (MATCH, SCORE)
    """

    result = process.extractOne(
            word, word_list, scorer=fp_ratio, score_cutoff=score_cutoff)
    if not result:
        return (None, None)
    return result
