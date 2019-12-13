import datetime
from dateutil.parser import parse
import json
import os
import pprint
import requests


ORG = 'https://api.github.com/orgs/firecracker-microvm'
REPO = 'https://api.github.com/repos/firecracker-microvm/firecracker'
OSDAY = datetime.datetime(2018,11,26,0,0,0)

TOKEN = 'INSERT-TOKEN-HERE'

FIRST_TIME_CONTRIB = 'FIRST_TIME_CONTRIBUTOR'
MEMBER = 'MEMBER'


def _github_resources(resource):
    all_resources = []
    page = 1
    while True:
        response = requests.get(
            '{}/{}?state=all&page={}&per_page=100'
            .format(REPO, resource, page),
            headers={
                'Authorization': 'token {}'.format(TOKEN),
                'Content-Type': 'application/json'
            }
        )            
        resources = json.loads(response.text or response.content)
        all_resources.extend(resources)
        if len(resources) < 100:
            break
        page += 1
    return all_resources


def comments(issue_no):
    all_resources = []
    page = 1
    while True:
        response = requests.get(
            '{}/issues/{}/comments?page={}&per_page=100'
            .format(REPO, issue_no, page),
            headers={
                'Authorization': 'token {}'.format(TOKEN),
                'Content-Type': 'application/json'
            }
        )            
        resources = json.loads(response.text or response.content)
        all_resources.extend(resources)
        if len(resources) < 100:
            break
        page += 1
    return all_resources


def pulls():
    return _github_resources('pulls')


def issues():
    return _github_resources('issues')


def is_community_contribution(contribution):
    return contribution['author_association'].strip().upper() != MEMBER


def is_first_time(contribution):
    return contribution['author_association'].strip().upper() == FIRST_TIME_CONTRIB


def resources_community(resources):
    return [resource for resource in resources if is_community_contribution(resource)]


def pulls_first_timers(pulls):
    return [pull for pull in pulls if is_first_time(pull)]


def is_post_open_sourcing(resource):
    create_date = parse(resource['created_at']).replace(tzinfo=OSDAY.tzinfo)
    return create_date > OSDAY


def post_open_sourcing(resources):
    return [resource for resource in resources if is_post_open_sourcing(resource)]


def main():
    all_pulls = []
    # TODO cmd line args for cache disable
    if not os.path.exists('pulls.json'):
        print('Getting pulls from GH api')
        with open('pulls.json', 'w') as pulls_json:
            all_pulls = pulls()
            pulls_json.write(json.dumps(all_pulls))
    else:
        print('Getting pulls from cached file')
        with open('pulls.json') as pulls_json:
            all_pulls = json.load(pulls_json)
    
    if not os.path.exists('issues.json'):
        print('Getting issues from GH api')
        with open('issues.json', 'w') as issues_json:
            all_issues = issues()
            issues_json.write(json.dumps(all_issues))
    else:
        print('Getting issues from cached file')
        with open('issues.json') as issues_json:
            all_issues = json.load(issues_json)

    # pp = pprint.PrettyPrinter(indent=4)

    comm_issues = post_open_sourcing(resources_community(all_issues))

    with open('issues.csv', 'w') as out_issues:
        out_issues.write('issue_no,issue_url,created_at,commented_at,closed_at\n')
        for issue in comm_issues:
            if '/issues/' in issue['html_url']:
                created_at = issue['created_at'].strip()
                closed_at = issue['closed_at']
                if closed_at:
                    closed_at = closed_at.strip()

                comms = comments(issue['number'])
                if len(comms) == 0:
                    first_comm = None
                else:
                    for comm in comms:
                        if comm['author_association'].strip().upper() == 'MEMBER':
                            first_comm = comm['created_at'].strip()
                            break
                
                if first_comm is None and closed_at is not None:
                    first_comm = closed_at
                
                if not first_comm:
                    first_comm = '2019-12-09T10:00:00Z'
                if not closed_at:
                    closed_at = '2019-12-09T10:00:00Z'

                out_issues.write('{},{},{},{},{}\n'.format(
                    issue['number'],
                    issue['html_url'],
                    parse(created_at).strftime('%Y-%m-%d'),
                    parse(first_comm).strftime('%Y-%m-%d'),
                    parse(closed_at).strftime('%Y-%m-%d')
                ))

    comm_pulls = post_open_sourcing(resources_community(all_issues))

    with open('pulls.csv', 'w') as out_pulls:
        out_pulls.write('pull_no,pull_url,created_at,commented_at,closed_at\n')
        for pr in comm_pulls:
            created_at = pr['created_at'].strip()
            closed_at = pr['closed_at']
            if closed_at:
                closed_at = closed_at.strip()

            comms = comments(pr['number'])
            if len(comms) == 0:
                first_comm = None
            else:
                for comm in comms:
                    if comm['author_association'].strip().upper() == 'MEMBER':
                        first_comm = comm['created_at'].strip()
                        break
            
            if first_comm is None and closed_at is not None:
                first_comm = closed_at
            
            if not first_comm:
                first_comm = '2019-12-09T10:00:00Z'
            if not closed_at:
                closed_at = '2019-12-09T10:00:00Z'

            out_pulls.write('{},{},{},{},{}\n'.format(
                pr['number'],
                pr['html_url'],
                parse(created_at).strftime('%Y-%m-%d'),
                parse(first_comm).strftime('%Y-%m-%d'),
                parse(closed_at).strftime('%Y-%m-%d')
            ))
    
    contributors = []
    for pr in comm_pulls:
        ctr = pr['user']['login'].strip()
        if ctr not in contributors:
            contributors.append(ctr)
    print('{} contributors'.format(len(contributors)))

    total_pulls = len(comm_issues)
    still_open = 0
    closed_later_than_1wk = 0

    for pr in comm_pulls:
        created_at = pr['created_at'].strip()
        closed_at = pr['closed_at']
        if closed_at:
            closed_at = closed_at.strip()
            age = (parse(closed_at) - parse(created_at)).days
            print('{} {}'.format(pr['number'], age))
            if age > 7:
                closed_later_than_1wk += 1
        else:
            still_open += 1
    print('{} {} {}'.format(still_open, closed_later_than_1wk, total_pulls))


if __name__ == '__main__':
    main()
