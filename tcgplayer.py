import copy
import math
import operator
import requests

from bisect import bisect_left
from collections import defaultdict
from functools import reduce

ACCESS_TOKEN = 'xEodnIqwY2Ak0ncn_cQrr48e4vIJCaewaD8ZXX0ehtAoxc14h7NOOclwik2Yjs5pXoRKQXs2XhZZ8tlJoy_Zd23z51Gf9cbF5lmC66CmO-EQo1qVHsLEHcQkq-qAVPpFQw-54dyWQPHIvoPamb9l1ZBAutLxXyj2QAbcI_s55FX-km7UJaVCdYd-NyYjJ4_3BX4I2tkKBYDzat0-AumVMX1fQT3M9PnzEAvtJ5VBagJj66EedoGP3qDyCq32XNdCJomp_-oyld1nRNGqKlusEA3k8wCOfjAGZASFxvIKUtxy5MVK_cTmowGK5sYH4jZnLjCKDA' # noqa
ROUND_MULTIPLIER = 100
TRANSFORM_ACCURACY = 1E+4
MAX_TRANSFORM_SIZE = 5E+6


def make_request(endpoint, data=None):
    # print(endpoint, data)
    response = requests.get(f"https://api.tcgplayer.com{endpoint}",
                            headers={
                                "Accept": "application/json",
                                "Authorization": f"bearer {ACCESS_TOKEN}"},
                            data=data)
    return response.json()


def get_all_results(endpoint, data=""):
    PER_REQUEST = 100

    results = []
    total_checked = 0
    total = 1
    while total_checked < total:
        response = make_request(endpoint + f"?offset={total_checked}&limit={PER_REQUEST}&{data}")
        results += response['results']
        total_checked = len(results)
        total = response['totalItems']
        print(total_checked, total)

    return results


def get_set_id(name=None, abbreviation=None):
    if name is None and abbreviation is None:
        raise Exception("Must specify at least one condition")

    groups = get_all_results("/catalog/categories/1/groups")

    for group in groups:
        if (abbreviation is not None and group['abbreviation'].lower() == abbreviation.lower()) \
                or (name is not None and group['name'].lower() == name.lower()):
            return group['groupId']
    raise Exception("Could not find the specified set")


def get_cards(setId):
    return get_all_results("/catalog/products",
                           f"groupId={setId}&getExtendedFields=true")


def get_rarity(card):
    for data in card['extendedData']:
        if data['displayName'] == 'Rarity':
            return data['value']
    return None


def add_pricing_to_cards(cards):
    PROCESS_PER_RUN = 100
    card_id_dict = {card['productId']: card for card in cards}
    card_ids = [str(card_id) for card_id in card_id_dict.keys()]

    processed_ids = set()
    foil_processed_ids = set()
    processed = []
    total_processed = 0
    while total_processed < len(card_ids):
        to_process = card_ids[total_processed:min(len(card_ids), total_processed + PROCESS_PER_RUN)]
        pricings = make_request("/pricing/product/{}".format(','.join(to_process)))

        for pricing in pricings['results']:
            if pricing['subTypeName'] == 'Normal':
                card_id = pricing['productId']
                if card_id in card_id_dict and card_id not in processed_ids:
                    card = card_id_dict[card_id]
                    card['pricing'] = pricing
                    processed.append(card)
                    processed_ids.add(card_id)
            elif pricing['subTypeName'] == 'Foil':
                card_id = pricing['productId']
                if card_id in card_id_dict and card_id not in foil_processed_ids:
                    card = card_id_dict[card_id]
                    card['foilPricing'] = pricing
                    foil_processed_ids.add(card_id)

        total_processed += PROCESS_PER_RUN
        print(total_processed, len(card_ids))

    processed = list(card for card in processed if card['productId'] in foil_processed_ids)

    return processed


def has_normal_rarity(card):
        return get_rarity(card) in ['C', 'U', 'R', 'M']


def round_dist(dist, round_to=ROUND_MULTIPLIER):
    if not dist:
        return [(0, 1)]
    result_dict = defaultdict(float)

    for value, weight in dist:
        result_dict[int(value * round_to)] += weight

    return sorted(((x / round_to, y) for x, y in result_dict.items()), key=lambda x: x[0])


def transform_distributions(transform, *distributions):
    distributions_sorted = sorted(enumerate(distributions), key=lambda x: len(x[1]), reverse=True)
    multipliers = list(ROUND_MULTIPLIER for _ in distributions)
    prev_sizes = list(len(x) for x in distributions)
    prev_averages = list(sum(list(x * y for x, y in dist)) for dist in distributions)
    dist_size = reduce(operator.mul, (len(x[1]) for x in distributions_sorted))
    print_final_dist = False
    start_size = dist_size
    while dist_size > MAX_TRANSFORM_SIZE:
        index, dist = distributions_sorted[0]
        mult = multipliers[index] = multipliers[index] / 2
        dist = round_dist(dist, mult)

        distributions_sorted[0] = (index, dist)
        distributions_sorted = sorted(distributions_sorted, key=lambda x: len(x[1]), reverse=True)
        dist_size = reduce(operator.mul, (len(x[1]) for x in distributions_sorted))

    distributions = list(x[1] for x in sorted(distributions_sorted, key=lambda x: x[0]))
    if print_final_dist:
        for i, dist in enumerate(distributions):
            new_average = sum(list(x * y for x, y in dist))
            print("Reduced dist", i, "from size", prev_sizes[i], "to", len(dist),
                  "With average value change", prev_averages[i], "to", new_average,
                  "Which percentagewise is", 100 * new_average / prev_averages[i],
                  "New multiplier is", multipliers[i])
        print("Started at size", start_size, "Final distributions are size", dist_size, "with sizes",
              list(len(x) for x in distributions), "and multipliers", multipliers)

    result_values = defaultdict(float)

    def recursive_transform(fixed_args, result_weight, remaining_distributions):
        if remaining_distributions:
            for card, weight in remaining_distributions[0]:
                recursive_transform([*fixed_args, card],
                                    result_weight * weight,
                                    remaining_distributions[1:])
        else:
            result_key = int(transform(*fixed_args) * ROUND_MULTIPLIER)
            result_values[result_key] += result_weight

    recursive_transform([], 1, distributions)
    min_prob = 1 / len(result_values) / TRANSFORM_ACCURACY

    average_value = sum(list(x * y for x, y in result_values.items())) / ROUND_MULTIPLIER
    values_list = list((x / ROUND_MULTIPLIER, y) for x, y in result_values.items() if y > min_prob)
    corrected_average_value = sum(list(x * y for x, y in values_list))
    if average_value - corrected_average_value > 0.01:
        print("POST TRIM", corrected_average_value, average_value, average_value - corrected_average_value,
              100 * corrected_average_value / average_value if average_value > 0 else 0)
    values_list.append((0, 1 - sum(list(x[1] for x in values_list))))
    return sorted(values_list, key=lambda x: x[0])


def repeat_transform_n(transform, n, distribution):
        auxilary = None
        # print(n)
        while n > 1:
            if n % 2 == 1:
                if auxilary is None:
                    auxilary = distribution
                else:
                    auxilary = transform_distributions(transform, distribution, auxilary)
            distribution = transform_distributions(transform, distribution, distribution)
            n = n // 2
            # print(n)

        if auxilary is None:
            return distribution
        else:
            return transform_distributions(transform, auxilary, distribution)


def print_stat_info(cards, designation):
    cards_count = len(cards)
    if not isinstance(cards[0], (list, tuple)):
        cards = list((x, 1 / cards_count) for x in cards)

    cumulative_sum = [cards[0][1]]
    for i in range(1, len(cards)):
        cumulative_sum.append(cumulative_sum[i - 1] + cards[i][1])

    cards_value = sum(card * weight for card, weight in cards)
    cards_std_dev = math.sqrt(sum(weight * (card - cards_value)**2 for card, weight in cards))
    cards_rel_std_dev = cards_std_dev / cards_value
    cards_deciles = list(cards[min(bisect_left(cumulative_sum, i / 10), cards_count - 1)][0] for i in range(11))

    print(designation, "Average:", f"${cards_value:.2f}")
    print(designation, "StdDev:", f"${cards_std_dev:.2f}")
    print(designation, "RelStdDev", f"{100 * cards_rel_std_dev:.1f}%")
    print(designation, "Deciles:", ' '.join(f"${x:.2f}" for x in cards_deciles))
    print()

    return cards_value, cards_std_dev, cards_rel_std_dev, cards_deciles


def print_rarity_stat_info(cards, rarity):
    cards_mid = sorted(card['pricing']['midPrice'] for card in cards)
    cards_market = sorted(card['pricing']['marketPrice'] for card in cards)

    mid_values = print_stat_info(cards_mid, f"{rarity} Mid")
    market_values = print_stat_info(cards_market, f"{rarity} Market")

    return mid_values, market_values


def print_pack_value_x_and_over(commons, uncommons, rares, mythics, threshold, foils=[], mid=True):
    COMMONS_PER_PACK = 10
    UNCOMMONS_PER_PACK = 3
    RARES_PER_PACK = 7 / 8
    MYTHICS_PER_PACK = 1 / 8
    commons_count = len(commons)
    uncommons_count = len(uncommons)
    rares_count = len(rares)
    mythics_count = len(mythics)

    pricing = 'marketPrice'
    source = 'Market'
    if mid:
        pricing = 'midPrice'
        source = 'Mid'

    commons_pre = list((card['pricing'][pricing], 1 / commons_count)
                       for card in commons
                       if card['pricing'][pricing] >= threshold)
    commons_pre.append((0, 1 - sum(list(weight for card, weight in commons_pre))))
    commons_pre = sorted(commons_pre, key=lambda x: x[0])
    commons_values = repeat_transform_n(lambda *args: sum(args), COMMONS_PER_PACK, commons_pre)

    uncommons_pre = list((card['pricing'][pricing], 1 / uncommons_count)
                         for card in uncommons
                         if card['pricing'][pricing] >= threshold)
    uncommons_pre.append((0, 1 - sum(list(weight for card, weight in uncommons_pre))))
    uncommons_pre = sorted(uncommons_pre, key=lambda x: x[0])
    uncommons_values = repeat_transform_n(lambda *args: sum(args), UNCOMMONS_PER_PACK, uncommons_pre)

    rare_slot = list((card['pricing'][pricing], RARES_PER_PACK / rares_count)
                     for card in rares
                     if card['pricing'][pricing] >= threshold) \
        + list((card['pricing'][pricing], MYTHICS_PER_PACK / mythics_count)
               for card in mythics
               if card['pricing'][pricing] >= threshold)
    rare_slot.append((0, 1 - sum(list(weight for card, weight in rare_slot))))
    rare_slot = sorted(rare_slot, key=lambda x: x[0])

    foils_value = list(card for card in foils if card[0] >= threshold)
    foils_value.append((0, 1 - sum(list(weight for card, weight in foils_value))))
    foils_value = sorted(foils_value, key=lambda x: x[0])

    pack = transform_distributions(lambda *args: sum(args), commons_values, uncommons_values, rare_slot, foils_value)

    print_stat_info(pack, f"Pack(${threshold:.2f} and over only) {source}")

    return pack


def create_foil_distribution(commons, uncommons, rares, mythics, foil_rarity, mid=True):
    FOIL_COMMON_RARITY = 11 / 15
    FOIL_UNCOMMON_RARITY = 1 / 5
    FOIL_RARE_RARITY = 7 / 120
    FOIL_MYTHIC_RARITY = 1 / 120
    commons_count = len(commons)
    uncommons_count = len(uncommons)
    rares_count = len(rares)
    mythics_count = len(mythics)

    pricing = 'marketPrice'
    if mid:
        pricing = 'midPrice'

    foils = list((card['foilPricing'][pricing], FOIL_COMMON_RARITY * foil_rarity / commons_count)
                 for card in commons) \
        + list((card['foilPricing'][pricing], FOIL_UNCOMMON_RARITY * foil_rarity / uncommons_count)
               for card in uncommons) \
        + list((card['foilPricing'][pricing], FOIL_RARE_RARITY * foil_rarity / rares_count)
               for card in rares) \
        + list((card['foilPricing'][pricing], FOIL_MYTHIC_RARITY * foil_rarity / mythics_count)
               for card in mythics)
    foils.append((0, 1 - sum(list(weight for card, weight in foils))))
    foils = sorted(foils, key=lambda x: x[0])

    return foils


def print_expected_pack_value(setId, foil_rarity=1 / 6):
    RARES_PER_PACK = 7 / 8
    MYTHICS_PER_PACK = 1 / 8

    cards = get_cards(setId)
    cards = [card for card in cards if has_normal_rarity(card)]
    cards = add_pricing_to_cards(cards)
    commons = [card for card in cards if get_rarity(card) == 'C']
    uncommons = [card for card in cards if get_rarity(card) == 'U']
    rares = [card for card in cards if get_rarity(card) == 'R']
    mythics = [card for card in cards if get_rarity(card) == 'M']

    common_mid, common_market = print_rarity_stat_info(commons, "Commons")
    uncommon_mid, uncommon_market = print_rarity_stat_info(uncommons, "Uncommons")
    rare_mid, rare_market = print_rarity_stat_info(rares, "Rares")
    mythic_mid, mythic_market = print_rarity_stat_info(mythics, "Mythics")

    foils_mid = []
    foils_market = []
    if foil_rarity > 0:
        foils_mid = create_foil_distribution(commons, uncommons, rares, mythics, foil_rarity, mid=True)
        foils_market = create_foil_distribution(commons, uncommons, rares, mythics, foil_rarity, mid=False)
        print_stat_info(foils_mid, "Foils Mid")
        print_stat_info(foils_market, "Foils Market")

    rares_count = len(rares)
    mythics_count = len(mythics)

    values_mid = sorted(list((card['pricing']['midPrice'], RARES_PER_PACK / rares_count)
                             for card in rares) +
                        list((card['pricing']['midPrice'], MYTHICS_PER_PACK / mythics_count)
                             for card in mythics),
                        key=lambda x: x[0])
    print_stat_info(values_mid, "Pack(Rare/Mythic only) Mid")

    values_market = sorted(list((card['pricing']['marketPrice'], RARES_PER_PACK / rares_count)
                                for card in rares) +
                           list((card['pricing']['marketPrice'], MYTHICS_PER_PACK / mythics_count)
                                for card in mythics),
                           key=lambda x: x[0])
    print_stat_info(values_market, "Pack(Rare/Mythic only) Market")

    pack_mid_50 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 0.50, foils_mid, mid=True)
    pack_market_50 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 0.50, foils_market, mid=False)

    pack_mid_1 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 1.00, foils_mid, mid=True)
    pack_market_1 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 1.00, foils_market, mid=False)

    pack_mid_2 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 2.00, foils_mid, mid=True)
    pack_market_2 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 2.00, foils_market, mid=False)

    return copy.copy(locals())


def get_box_price(setId, packs_per_box=36, foil_rarity=1 / 6):
    dists = print_expected_pack_value(setId, foil_rarity=foil_rarity)

    box_mid_50 = repeat_transform_n(lambda *args: sum(args), packs_per_box, dists['pack_mid_50'])
    print_stat_info(box_mid_50, "Box Mid($0.50 and over only)")
    box_market_50 = repeat_transform_n(lambda *args: sum(args), packs_per_box, dists['pack_market_50'])
    print_stat_info(box_market_50, "Box Market($0.50 and over only)")

    box_mid_2 = repeat_transform_n(lambda *args: sum(args), packs_per_box, dists['pack_mid_2'])
    print_stat_info(box_mid_2, "Box Mid($2.00 and over only)")
    box_market_2 = repeat_transform_n(lambda *args: sum(args), packs_per_box, dists['pack_market_2'])
    print_stat_info(box_market_2, "Box Market($2.00 and over only)")
