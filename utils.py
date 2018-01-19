import numpy as np


def calculate_score(run):
    advantages = run['advantages']

    # Mean
    mean = np.mean(advantages)
    if mean == 0: return -100  # no holders allowed
    return mean

    ## Last advantage
    # return advantages[-1]

    # Max number of consecutive positives
    score, curr_consec = 0, 0
    for i, adv in enumerate(advantages):
        if adv > 0:
            curr_consec += 1
            continue
        if curr_consec > score:
            score = curr_consec
        curr_consec = 0
    return score
