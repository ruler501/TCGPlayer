#!/usr/bin/env python3

import bisect
import copy
import math
import operator
import requests

from collections import defaultdict
from functools import reduce

from sortedcontainers import SortedDict, SortedList

ACCESS_TOKEN='oVnFSf4f-YoXhzrctn_PyOaFW7WdmSXfSg4LzlkcTG8RbEeWQlQtKHaxpHBDaH4p8Cf_HkL8EL35nrCwgx-ZJw4UN0tPLJFaXszub4JqK3gZBUf6qvVHq0ckNZ8ah-kWrd1VdoK7hMUmngfdEeiMipCwWyK7ZyEc8rHJGIiI_rEv92UQeiJQT3-u2lnW-xQbvghdiOVieqW--ekKIaca7XAGTJ_uP7awUSIruTyrYuQF9HwYx_LImIopuUFmos8aKmjGCuvqqT3lAeg-GqDFzx8GZS03EdyJHCglksEybwWs1R4yzDDWtQUH7LzT7FtyJ385KA'  # noqa
MAX_TRANSFORM_SIZE = 1E+6


def get_access_token():
    global ACCESS_TOKEN

    response = requests.post("https://api.tcgplayer.com/token",
                             headers={
                                 "Content-Type": "application/json",
                                 "Accept": "application/json"},
                             data="grant_type=client_credentials&client_id=D1694E24-A9F3-4AF4-8340-5A7C51AA02CC&client_secret=7A9F54EF-5EF6-4398-B2E8-AE7FC3488F3E")  # noqa

    ACCESS_TOKEN = response.json()['access_token']
    print(ACCESS_TOKEN)


def make_request(endpoint, data=None):
    print(f"https://api.tcgplayer.com/v1.17.0{endpoint}", data)
    response = requests.get(f"https://api.tcgplayer.com/v1.17.0{endpoint}",
                            headers={
                                "Accept": "application/json",
                                "Authorization": f"bearer {ACCESS_TOKEN}"},
                            data=data)
    print(response.text)
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


def get_cards_with_pricing(setId):
    cards = get_all_results("/catalog/products",
                            f"groupId={setId}&getExtendedFields=true")
    return add_pricing_to_cards(cards)


def get_rarity(card):
    for data in card['extendedData']:
        if data['displayName'] == 'Rarity':
            return data['value']
    return None


def add_pricing_to_cards(cards):
    PROCESS_PER_RUN = 37
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
            if pricing['marketPrice'] is None or pricing['midPrice'] is None:
                continue
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


# @profile  # noqa
def round_dist(dist, round_to=100):
    if not dist:
        return [(0, 1)]
    result_dict = defaultdict(float)

    for value, weight in dist:
        result_dict[int(value * round_to)] += weight

    return sorted(((x / round_to, y) for x, y in result_dict.items()), key=lambda x: x[0])


# @profile  # noqa
def trim_dist(dist, max_size):
    dist = round_dist(dist, 10)

    indexes = SortedList(i for i, x in sorted(enumerate(dist), key=lambda x: x[1][1])[:-max_size])
    bad_values = SortedList(dist[x][0] for x in indexes)
    bad_weights = list(dist[x][1] for x in indexes)

    result_dict = SortedDict(x for x in dist if x[0] not in bad_values)

    for value, weight in zip(bad_values, bad_weights):
        index = result_dict.bisect(value)

        closest_above = None
        closest_below = None
        try:
            closest_above = result_dict.iloc[index]
        except:
            pass
        try:
            closest_below = result_dict.iloc[index - 1]
        except:
            pass

        if (closest_above is not None) and \
                ((closest_below is None) or abs(value - closest_above) < abs(value - closest_below)):
            result_value = closest_above
        elif closest_below is not None:
            result_value = closest_below
        else:
            print("BROKEN", len(bad_values), value, index, len(result_dict))
            print(result_dict)
            raise Exception("Could not find a closest value to trim from")

        result_weight = result_dict[result_value]

        final_value = (result_weight * result_value + weight * value) / (result_weight + weight)
        if final_value in result_dict and final_value != result_value:
            result_dict[final_value] += result_weight + weight
        else:
            result_dict[final_value] = result_weight + weight

        if final_value != result_value:
            del result_dict[result_value]
    return round_dist(sorted(((x, y) for x, y in result_dict.items()), key=lambda x: x[0]), 10)


# @profile  # noqa
def sum_distributions(*distributions):
    prev_sizes = list(len(x) for x in distributions)
    # prev_averages = list(sum(list(x * y for x, y in dist)) for dist in distributions)
    dist_size = reduce(operator.mul, (len(x) for x in distributions))
    print_final_dist = False
    start_size = dist_size
    if dist_size > MAX_TRANSFORM_SIZE:
        relative_size = MAX_TRANSFORM_SIZE / dist_size
        per_dist_relative = relative_size ** (1 / len(distributions))
        # print(per_dist_relative, "trimming per dist required")
        distributions = list(trim_dist(dist, int(len(dist) * per_dist_relative)) for dist in distributions)
    dist_size = reduce(operator.mul, (len(x) for x in distributions))
    if print_final_dist and start_size != dist_size:
        prev_averages = None
        for i, dist in enumerate(distributions):
            if prev_sizes[i] != len(dist):
                new_average = sum(list(x * y for x, y in dist))
                if prev_averages[i] - new_average > 0.01:
                    print("Reduced dist", i, "from size", prev_sizes[i], "to", len(dist),
                          "With average value change", prev_averages[i], "to", new_average,
                          "Which is", prev_averages[i] - new_average,
                          "Which percentagewise is",
                          100 * new_average / prev_averages[i] if prev_averages[i] > 0 else "inf")
        print("Started at size", start_size, "Final distributions are size", dist_size, "with sizes",
              list(len(x) for x in distributions))

    result_values = defaultdict(float)
    max_index = len(distributions)

    # @profile  # noqa
    def recursive_transform(result_key=0, result_weight=1, index=0):
        if index < max_index:
            for value, weight in distributions[index]:
                recursive_transform(result_key + value,
                                    result_weight * weight,
                                    index + 1)
        else:
            result_values[result_key] += result_weight

    recursive_transform()

    min_prob = 1 / len(result_values) / 1000

    values_list = list((x, y) for x, y in result_values.items() if y > min_prob)
    values_list.append((0, 1 - sum(list(x[1] for x in values_list))))
    return sorted(values_list, key=lambda x: x[0])


def dist_times_n(n, distribution):
        auxilary = None
        # print(n)
        while n > 1:
            if n % 2 == 1:
                if auxilary is None:
                    auxilary = distribution
                else:
                    auxilary = sum_distributions(distribution, auxilary)
            distribution = sum_distributions(distribution, distribution)
            n = n // 2
            # print(n)

        if auxilary is None:
            return distribution
        else:
            return sum_distributions(auxilary, distribution)


def print_stat_info(cards, designation):
    cards_count = len(cards)
    if not isinstance(cards[0], (list, tuple)):
        cards = list((x, 1 / cards_count) for x in cards)

    cumulative_sum = [cards[0][1]]
    for i in range(1, len(cards)):
        cumulative_sum.append(cumulative_sum[i - 1] + cards[i][1])

    cards_value = sum(card * weight for card, weight in cards)
    cards_std_dev = math.sqrt(sum(weight * (card - cards_value)**2 for card, weight in cards))
    cards_rel_std_dev = cards_std_dev / cards_value if cards_value > 0 else 0
    cards_deciles = list(cards[min(bisect.bisect_left(cumulative_sum, i / 10), cards_count - 1)][0] for i in range(11))

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
    commons_values = dist_times_n(COMMONS_PER_PACK, commons_pre)

    uncommons_pre = list((card['pricing'][pricing], 1 / uncommons_count)
                         for card in uncommons
                         if card['pricing'][pricing] >= threshold)
    uncommons_pre.append((0, 1 - sum(list(weight for card, weight in uncommons_pre))))
    uncommons_pre = sorted(uncommons_pre, key=lambda x: x[0])
    uncommons_values = dist_times_n(UNCOMMONS_PER_PACK, uncommons_pre)

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

    pack_1 = sum_distributions(commons_values, uncommons_values)
    print_stat_info(pack_1, f"Common/Uncommon slots(${threshold:.2f} and over only) {source}")

    pack_2 = sum_distributions(rare_slot, foils_value)
    pack = sum_distributions(pack_1, pack_2)

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
        print_stat_info(foils_mid, "Foil Slot Mid")
        print_stat_info(foils_market, "Foil Slot Market")

    rares_count = len(rares)
    mythics_count = len(mythics)

    values_mid = sorted(list((card['pricing']['midPrice'], RARES_PER_PACK / rares_count)
                             for card in rares) +
                        list((card['pricing']['midPrice'], MYTHICS_PER_PACK / mythics_count)
                             for card in mythics),
                        key=lambda x: x[0])
    print_stat_info(values_mid, "Rare Slot Mid")

    values_market = sorted(list((card['pricing']['marketPrice'], RARES_PER_PACK / rares_count)
                                for card in rares) +
                           list((card['pricing']['marketPrice'], MYTHICS_PER_PACK / mythics_count)
                                for card in mythics),
                           key=lambda x: x[0])
    print_stat_info(values_market, "Rare Slot Market")

    pack_mid_50 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 0.50, foils_mid, mid=True)
    pack_market_50 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 0.50, foils_market, mid=False)

    pack_mid_1 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 1.00, foils_mid, mid=True)
    pack_market_1 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 1.00, foils_market, mid=False)

    pack_mid_2 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 2.00, foils_mid, mid=True)
    pack_market_2 = print_pack_value_x_and_over(commons, uncommons, rares, mythics, 2.00, foils_market, mid=False)

    return copy.copy(locals())


def get_box_price(setId, packs_per_box=36, foil_rarity=1 / 6):
    dists = print_expected_pack_value(setId, foil_rarity=foil_rarity)

    box_mid_50 = dist_times_n(packs_per_box, dists['pack_mid_50'])
    print_stat_info(box_mid_50, "Box Mid($0.50 and over only)")
    box_market_50 = dist_times_n(packs_per_box, dists['pack_market_50'])
    print_stat_info(box_market_50, "Box Market($0.50 and over only)")

    box_mid_2 = dist_times_n(packs_per_box, dists['pack_mid_2'])
    print_stat_info(box_mid_2, "Box Mid($2.00 and over only)")
    box_market_2 = dist_times_n(packs_per_box, dists['pack_market_2'])
    print_stat_info(box_market_2, "Box Market($2.00 and over only)")


def get_total_value(cards):
    return \
        {
            'regular_mid': sum([card['pricing']['midPrice'] for card in cards]),
            'regular_market': sum([card['pricing']['marketPrice'] for card in cards]),
            'foil_mid': sum([card['foilPricing']['midPrice'] for card in cards]),
            'foil_market': sum([card['foilPricing']['marketPrice'] for card in cards]),
        }
