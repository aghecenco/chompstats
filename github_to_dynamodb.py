import datetime
from dateutil.parser import parse
from enum import Enum
import json
from math import ceil
import re


PULLS_TABLE_NAME = 'FirecrackerPulls'
ISSUES_TABLE_NAME = 'FirecrackerIssues'
PULLS_JSON = 'json/pulls.json'
ISSUES_JSON = 'json/issues.json'
TODAY = datetime.datetime.now()
# DynamoDB and empty strings, a sad love-hate story.
EMPTY_STRING = 'EMPTY_STRING'

class ItemType(Enum):
    PR = 1
    ISSUE = 2


def pr_state(pr):
    if pr['state'].strip().lower() == 'open':
        return 'open'
    elif pr['merged_at'] is not None:
        return 'merged'
    return 'dropped'


def issue_state(issue, merged_prs):
    if issue['state'].strip().lower() == 'open':
        return 'open'
    # If the issue was closed by a commit, we can get that from its events.
    evts = json.load(open('json/issue_{}_events.json'.format(issue['number'])))
    for ev in evts:
        if ev['event'].strip().lower() == 'closed' and ev['commit_id'] is not None:
            return 'implemented'
    # If the issue was closed when a PR with the keywords "Fixes" or "Closes"
    # was merged, that info is not easily accessible.
    # It's missing from the /issues API and only somewhat accessible from the
    # PR API.
    for pr in merged_prs:
        for keyword in ['Fixes', 'Closes']:
            fixes = re.findall('{} #[0-9]+'.format(keyword), pr['body'])
            issue_nos = [re.findall('[0-9]+', fix) for fix in fixes]
            # Flatten
            issue_nos = [int(iss) for iss_list in issue_nos for iss in iss_list]
            if issue['number'] in issue_nos:
                return 'implemented'
    return 'dropped'


def state(item, item_type=ItemType.PR, merged_prs=[]):
    if item_type == ItemType.PR:
        return pr_state(item)
    elif item_type == ItemType.ISSUE:
        return issue_state(item, merged_prs)
    raise Exception('invalid item type {}'.format(item_type))


def source(pr):
    if pr['author_association'].strip().lower() == 'member':
        return 'team'
    return 'community'


def days_delta(start, end):
    return (end - start).days


def age(pr):
    created_at = parse(pr['created_at']).replace(tzinfo=TODAY.tzinfo)
    if pr['closed_at'] is not None:
        closed_at = parse(pr['closed_at']).replace(tzinfo=TODAY.tzinfo)
        return days_delta(created_at, closed_at)
    return days_delta(created_at, TODAY)


def answer(comms):
    team_comms = [c for c in comms if c['author_association'].strip().lower() == 'member']
    team_comms_sorted = sorted(team_comms, key=lambda c: c['created_at'])
    if len(team_comms_sorted) > 0:
        return team_comms_sorted[0]
    else:
        return None


def item_internal(item, comms, item_type=ItemType.PR, merged_prs=[]):
    item_short = {'number' : item['number']}
    item_short['url'] = item['html_url'].strip()
    item_short['closed_at'] = item['closed_at']
    item_short['created_at'] = item['created_at']
    item_short['author'] = item['user']['login'].strip()

    item_short['state'] = state(item, item_type, merged_prs)
    item_short['source'] = source(item)
    item_short['age'] = age(item)

    ans = answer(comms)
    if ans is None:
        item_short['answered'] = False
        item_short['answer_url'] = None
        item_short['unanswered_age'] = item_short['age']
    else:
        item_short['answered'] = True
        item_short['answer_url'] = ans['html_url'].strip()
        item_short['unanswered_age'] = days_delta(parse(ans['created_at']).replace(tzinfo=TODAY.tzinfo), TODAY)

    return item_short


def mkitem_dynamo(item):
    return {
        'Item': {
            'number': { 'S': '{}'.format(item['number']) },
            'url': { 'S': item['url'] },
            'closed_at': { 'S': item['closed_at'] if item['closed_at'] is not None else EMPTY_STRING },
            'created_at': { 'S': item['created_at'] },
            'author': { 'S': item['author'] },
            'state': { 'S': item['state'] },
            'source': { 'S': item['source'] },
            'age': { 'N': '{}'.format(item['age']) },
            'answered': { 'BOOL': item['answered'] },
            'answer_url': { 'S': item['answer_url'] if item['answer_url'] is not None else EMPTY_STRING },
            'unanswered_age': { 'N': '{}'.format(item['unanswered_age']) }
        }
    }


def process_pulls():
    pulls = json.load(open(PULLS_JSON))
    pulls_internal = []
    for pr in pulls:
        comms = json.load(open('json/pr_{}_comments.json'.format(pr['number'])))
        pulls_internal.append(item_internal(pr, comms))
    return pulls_internal, pulls


def process_issues(merged_prs):
    issues = json.load(open(ISSUES_JSON))
    issues_internal = []
    for issue in issues:
        comms = json.load(open('json/issue_{}_comments.json'.format(issue['number'])))
        issues_internal.append(item_internal(issue, comms, item_type=ItemType.ISSUE, merged_prs=merged_prs))
    return issues_internal


def dynamodb_batch_req(reqs, table_name):
    curr_idx = 0
    while curr_idx < len(reqs):
        curr_idx_end = min(curr_idx + 25, len(reqs))
        batch_reqs = reqs[curr_idx:curr_idx_end]
        with open('{}_{}_{}.json'.format(table_name, curr_idx, curr_idx_end), 'w') as dynamo_pr_out:
            json.dump({ table_name: batch_reqs }, dynamo_pr_out)
        curr_idx += 25


def dynamo_req(items):
    return [ { 'PutRequest': mkitem_dynamo(item) } for item in items]


def write_dynamo_reqs(items, table_name):
    dynamodb_batch_req(dynamo_req(items), table_name)


def created_at(item):
    return parse(item['created_at']).replace(tzinfo=TODAY.tzinfo)


def gnuplot_data(items):
    # Only look in 2020
    START_DATE = datetime.datetime(2020, 1, 1, 0, 0, 1)
    items_tracked = [it for it in items if created_at(it).year == 2020]

    num_days = days_delta(START_DATE, TODAY)
    answered_community = {}
    answered_internal = {}
    unanswered_community = {}
    unanswered_internal = {}

    for day in range(num_days):
        items_this_day = [
            it for it in items_tracked if days_delta(START_DATE, created_at(it)) == day
        ]
        it_answered = [it for it in items_this_day if it['answered']]
        it_unanswered = [it for it in items_this_day if not it['answered']]

        it_answered_community = [it for it in it_answered if it['source'] == 'community']
        it_answered_internal = [it for it in it_answered if it['source'] == 'internal']
        it_unanswered_community = [it for it in it_unanswered if it['source'] == 'community']
        it_unanswered_internal = [it for it in it_unanswered if it['source'] == 'internal']

        ages_answered_community = [it['age'] for it in it_answered_community]
        ages_answered_internal = [it['age'] for it in it_answered_internal]
        ages_unanswered_community = [it['age'] for it in it_unanswered_community]
        ages_unanswered_internal = [it['age'] for it in it_unanswered_internal]

        if len(ages_answered_community) > 0:
            answered_community[day] = max(ages_answered_community)
        if len(ages_answered_internal) > 0:
            answered_internal[day] = max(ages_answered_internal)
        if len(ages_unanswered_community) > 0:
            unanswered_community[day] = max(ages_unanswered_community)
        if len(ages_unanswered_internal) > 0:
            unanswered_internal[day] = max(ages_unanswered_internal)
    
    return answered_community, answered_internal, unanswered_community, unanswered_internal


def write_gnuplot_data(pulls, issues):
    issues_answered_community, _, issues_unanswered_community, _ = gnuplot_data(issues)
    prs_answered_community, _, prs_unanswered_community, _ = gnuplot_data(pulls)

    answered_community = {}
    unanswered_community = {}

    with open('answered_community_issues.data', 'w') as out:
        out.write('# day age\n')
        for day in issues_answered_community:
            out.write('{} {}\n'.format(day, issues_answered_community[day]))
            answered_community[day] = issues_answered_community[day]
    with open('unanswered_community_issues.data', 'w') as out:
        out.write('# day age\n')
        for day in issues_unanswered_community:
            out.write('{} {}\n'.format(day, issues_unanswered_community[day]))
            unanswered_community[day] = issues_unanswered_community[day]
    
    with open('answered_community_pulls.data', 'w') as out:
        out.write('# day age\n')
        for day in prs_answered_community:
            out.write('{} {}\n'.format(day, prs_answered_community[day]))
            if day not in answered_community:
                answered_community[day] = 0
            answered_community[day] += prs_answered_community[day]

    with open('unanswered_community_pulls.data', 'w') as out:
        out.write('# day age\n')
        for day in prs_unanswered_community:
            out.write('{} {}\n'.format(day, prs_unanswered_community[day]))
            if day not in unanswered_community:
                unanswered_community[day] = 0
            unanswered_community[day] += prs_unanswered_community[day]
    
    with open('answered_community.data', 'w') as out:
        out.write('# day age\n')
        for day in answered_community:
            out.write('{} {}\n'.format(day, answered_community[day]))
    with open('unanswered_community.data', 'w') as out:
        out.write('# day age\n')
        for day in unanswered_community:
            out.write('{} {}\n'.format(day, unanswered_community[day]))

def main():
    pulls_internal, pulls_raw = process_pulls()
    issues_internal = process_issues([pr for pr in pulls_raw if state(pr) == 'merged'])

    write_gnuplot_data(pulls_internal, issues_internal)
    
    # write_dynamo_reqs(pulls_internal, PULLS_TABLE_NAME)
    # write_dynamo_reqs(issues_internal, ISSUES_TABLE_NAME)


if __name__ == '__main__':
    main()


# In batches of 25:
# aws dynamodb batch-write-item --request-items file://FirecrackerPulls_125_150.json
# {
#    "UnprocessedItems": {}
#}
