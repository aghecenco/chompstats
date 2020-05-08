import datetime
from dateutil.parser import parse
import json


PULLS_TABLE_NAME = 'FirecrackerPulls'
PULLS_JSON = 'json/pulls.json'
TODAY = datetime.datetime.now()
# DynamoDB and empty strings, a sad love-hate story.
EMPTY_STRING = 'EMPTY_STRING'


def state(pr):
    if pr['state'].strip().lower() == 'open':
        return 'open'
    elif pr['merged_at'] is not None:
        return 'merged'
    return 'dropped'


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


def transit_mkprdb(pr, comms):
    prdb = {'number' : pr['number']}
    prdb['url'] = pr['html_url'].strip()
    prdb['closed_at'] = pr['closed_at']
    prdb['created_at'] = pr['created_at']
    prdb['author'] = pr['user']['login'].strip()

    prdb['state'] = state(pr)
    prdb['source'] = source(pr)
    prdb['age'] = age(pr)

    ans = answer(comms)
    if ans is None:
        prdb['answered'] = False
        prdb['answer_url'] = None
        prdb['unanswered_age'] = prdb['age']
    else:
        prdb['answered'] = True
        prdb['answer_url'] = ans['html_url'].strip()
        prdb['unanswered_age'] = days_delta(parse(ans['created_at']).replace(tzinfo=TODAY.tzinfo), TODAY)

    return prdb


def mkprdb(pr, comms):
    tmp_pr = transit_mkprdb(pr, comms)
    prdb = {
        'Item': {
            'number': { 'S': '{}'.format(tmp_pr['number']) },
            'url': { 'S': tmp_pr['url'] },
            'closed_at': { 'S': tmp_pr['closed_at'] if tmp_pr['closed_at'] is not None else EMPTY_STRING },
            'created_at': { 'S': tmp_pr['created_at'] },
            'author': { 'S': tmp_pr['author'] },
            'state': { 'S': tmp_pr['state'] },
            'source': { 'S': tmp_pr['source'] },
            'age': { 'N': '{}'.format(tmp_pr['age']) },
            'answered': { 'BOOL': tmp_pr['answered'] },
            'answer_url': { 'S': tmp_pr['answer_url'] if tmp_pr['answer_url'] is not None else EMPTY_STRING },
            'unanswered_age': { 'N': '{}'.format(tmp_pr['unanswered_age']) }
        }
    }
    return prdb


def main():
    pulls = json.load(open(PULLS_JSON))
    pulls_reqs = []
    for pr in pulls:
        comms = json.load(open('json/pr_{}_comments.json'.format(pr['number'])))
        pr_db = mkprdb(pr, comms)
        req = { 'PutRequest': pr_db }
        pulls_reqs.append(req)

    curr_idx = 0
    while curr_idx < len(pulls_reqs):
        curr_idx_end = min(curr_idx + 25, len(pulls_reqs))
        batch_pulls_reqs = pulls_reqs[curr_idx:curr_idx_end]
        with open('{}_{}_{}.json'.format(PULLS_TABLE_NAME, curr_idx, curr_idx_end), 'w') as dynamo_pr_out:
            json.dump({ PULLS_TABLE_NAME: batch_pulls_reqs }, dynamo_pr_out)
        curr_idx += 25


if __name__ == '__main__':
    main()


# In batches of 25:
# aws dynamodb batch-write-item --request-items file://FirecrackerPulls_125_150.json
# {
#    "UnprocessedItems": {}
#}
