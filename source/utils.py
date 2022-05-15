from thefuzz import fuzz
from thefuzz import process
from thefuzz import utils


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


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
    """Uses thefuzz to see if word is close to entries in word_list

    Returns a tuple of (MATCH, SCORE)
    """

    result = process.extractOne(
        word, word_list, scorer=fp_ratio, score_cutoff=score_cutoff)
    if not result:
        return None, None
    return result

def get_partial_matches(word: str, word_list: list, score_cutoff: int = 75, limit: int = 25):
    """Uses thefuzz to see if word is close to entries in word_list

    Returns a list of best partial matches
    """

    result = process.extractBests(
        word, word_list, scorer=fuzz.partial_ratio,
        score_cutoff=score_cutoff, limit=limit)
    if result:
        return [match[0] for match in result]
    return result
