import datetime
from dateutil.parser import parse
from enum import Enum
import json
import os
import pprint
import requests


ORG = 'https://api.github.com/orgs/rust-vmm'

TOKEN = 'INSERT-TOKEN-HERE'

CACHE = {
    'repos': 'repos.json'
}

def get_repos(use_cache=True):
    cache = CACHE['repos']
    if use_cache and os.path.exists(cache):
        return json.load(open(cache))
    else:
        response = requests.get('{}/repos'.format(ORG))
        repos = json.loads(response.text or response.content)
        with open(cache, 'w') as cache_out:
            json.dump(repos, cache_out)
        return repos


def _github_resources(repo, resource):
    all_resources = []
    page = 1
    per_page = 100
    while True:
        response = requests.get(
            '{}/{}?state=all&page={}&per_page={}'
            .format(repo, resource, page, per_page),
            headers={
                'Authorization': 'token {}'.format(TOKEN),
                'Content-Type': 'application/json'
            }
        )            
        resources = json.loads(response.text or response.content)
        all_resources.extend(resources)
        if len(resources) < per_page:
            break
        page += 1
    return all_resources


def get_resources(repo, resource, use_cache=True):
    repo_name = repo['name']
    repo_url = repo['url']
    cache_key = '{}_{}'.format(repo_name, resource)
    if cache_key not in CACHE:
        CACHE[cache_key] = '{}.json'.format(cache_key)
    cache = CACHE[cache_key]

    if use_cache and os.path.exists(cache):
        return json.load(open(cache))
    else:
        resources = _github_resources(repo_url, resource)
        with open(cache, 'w') as cache_out:
            json.dump(resources, cache_out)
        return resources


def get_comments(repo, resource, use_cache=True):
    all_comments = []
    page = 1
    per_page = 100
    url = resource['comments_url']
    repo_name = repo['name']
    if '/issues/' in resource['html_url']:
        res_type = 'issues'
    else:
        res_type = 'pulls'
    res_type = '{}_{}'.format(res_type, resource['number'])

    cache_key = '{}_{}_comments'.format(repo_name, res_type)
    if cache_key not in CACHE:
        CACHE[cache_key] = '{}.json'.format(cache_key)
    cache = CACHE[cache_key]

    if use_cache and os.path.exists(cache):
        return json.load(open(cache))
    else:
        while True:
            response = requests.get(
                '{}?page={}&per_page={}'.format(url, page, per_page),
                headers={
                    'Authorization': 'token {}'.format(TOKEN),
                    'Content-Type': 'application/json'
                }
            )            
            comments = json.loads(response.text or response.content)
            all_comments.extend(comments)
            if len(comments) < per_page:
                break
            page += 1
        with open(cache, 'w') as cache_out:
            json.dump(all_comments, cache_out)
        return all_comments


def add_contribution(contributions, contribution, type):
    author = contribution['user']['login']
    if author not in contributions:
        contributions[author] = []
    contributions[author].append({
        'type': type,
        'url': contribution['html_url']
    })


def day_since_epoch(tstamp):
    return (
        tstamp - datetime.datetime(1970, 1, 1).replace(tzinfo=tstamp.tzinfo)
    ).days + 1


def add_trend(trends, companies, author, contribution, contrib_type):
    company = companies[author]
    if companies[author] not in trends:
        return
    created_at = parse(contribution['created_at'])
    day = day_since_epoch(created_at)
    week = int(day / 7) - 2556

    if week not in trends[company][contrib_type]:
        trends[company][contrib_type][week] = 0
    trends[company][contrib_type][week] += 1
    if week not in trends[company]['TOTAL']:
        trends[company]['TOTAL'][week] = 0
    trends[company]['TOTAL'][week] += 1


def main():
    pp = pprint.PrettyPrinter(indent=4)
    
    CONTRIBUTIONS = {}
    CONTRIB_TYPE = Enum('CONTRIB_TYPE', 'PR ISSUE REVIEW COMMENT')
    
    COMPANIES = json.load(open('companies.json'))
    CONTRIB_PER_COMPANY = {}

    # contribution:
    # {
    #     'type': PR | ISSUE | COMMENT | REVIEW,
    #     'url': url
    # }

    TRENDS = {
        'AWS': {},
        'Intel': {},
        'Alibaba': {},
        'RedHat': {}
    }
    for comp in TRENDS:
        TRENDS[comp]['PR'] = {}
        TRENDS[comp]['ISSUE'] = {}
        TRENDS[comp]['REVIEW'] = {}
        TRENDS[comp]['COMMENT'] = {}
        TRENDS[comp]['TOTAL'] = {}

    all_repos = get_repos()
    # pp.pprint(all_repos)

    for repo in all_repos:
        # repo_name_prs.json
        prs = get_resources(repo, 'pulls')
        for pr in prs:
            for reviewer in pr['requested_reviewers']:
                reviewer_login = reviewer['login']
                if reviewer_login not in CONTRIBUTIONS:
                    CONTRIBUTIONS[reviewer_login] = []
                CONTRIBUTIONS[reviewer_login].append({
                    'type': CONTRIB_TYPE.REVIEW,
                    'url': pr['html_url']
                })
                add_trend(TRENDS, COMPANIES, reviewer_login, pr, 'REVIEW')

            add_contribution(CONTRIBUTIONS, pr, CONTRIB_TYPE.PR)
            author = pr['user']['login']
            add_trend(TRENDS, COMPANIES, author, pr, 'PR')

            comms = get_comments(repo, pr)
            for comm in comms:
                add_contribution(CONTRIBUTIONS, comm, CONTRIB_TYPE.COMMENT)
                author = comm['user']['login']
                add_trend(TRENDS, COMPANIES, author, comm, 'COMMENT')

        issues = get_resources(repo, 'issues')
        for issue in issues:
            if '/issues/' in issue['html_url']:
                # https://developer.github.com/v3/issues/
                # Note: GitHub's REST API v3 considers every pull request an 
                # issue, but not every issue is a pull request.
                add_contribution(CONTRIBUTIONS, issue, CONTRIB_TYPE.ISSUE)
                
                author = issue['user']['login']
                add_trend(TRENDS, COMPANIES, author, issue, 'ISSUE')

                comms = get_comments(repo, issue)
                for comm in comms:
                    add_contribution(CONTRIBUTIONS, comm, CONTRIB_TYPE.COMMENT)
                    author = comm['user']['login']
                    add_trend(TRENDS, COMPANIES, author, comm, 'COMMENT')

    for company in TRENDS:
        for contrib_type in TRENDS[company]:
            out = open('{}_{}.out'.format(company, contrib_type), 'w')
            for week in sorted(TRENDS[company][contrib_type]):
                out.write('{} {}\n'.format(
                    week, TRENDS[company][contrib_type][week]
                ))

    return

    ############################################

    out = open('contributions.csv', 'w')
    out_comp = open('contributions_agg.csv', 'w')

    out.write('github_user,company,pulls,issues,reviews,comments,total\n')
    out_comp.write('company,pulls,issues,reviews,comments,total\n')

    for author in CONTRIBUTIONS:
        total_pulls = 0
        total_issues = 0
        total_reviews = 0
        total_comments = 0
        for contrib in CONTRIBUTIONS[author]:
            if contrib['type'] == CONTRIB_TYPE.PR:
                total_pulls += 1
            elif contrib['type'] == CONTRIB_TYPE.ISSUE:
                total_issues += 1
            elif contrib['type'] == CONTRIB_TYPE.REVIEW:
                total_reviews += 1
            else:
                total_comments += 1
        total = total_pulls + total_issues + total_reviews + total_comments
        out.write('{},{},{},{},{},{},{}\n'.format(
            author, COMPANIES[author],
            total_pulls, total_issues, total_reviews, total_comments,
            total
        ))
        if COMPANIES[author] not in CONTRIB_PER_COMPANY:
            CONTRIB_PER_COMPANY[COMPANIES[author]] = {
                'pulls': 0,
                'issues': 0,
                'reviews': 0,
                'comments': 0,
                'total': 0
            }
        CONTRIB_PER_COMPANY[COMPANIES[author]]['pulls'] += total_pulls
        CONTRIB_PER_COMPANY[COMPANIES[author]]['issues'] += total_issues
        CONTRIB_PER_COMPANY[COMPANIES[author]]['reviews'] += total_reviews
        CONTRIB_PER_COMPANY[COMPANIES[author]]['comments'] += total_comments
        CONTRIB_PER_COMPANY[COMPANIES[author]]['total'] += total
    
    for company in CONTRIB_PER_COMPANY:
        out_comp.write('{},{},{},{},{},{}\n'.format(
            company,
            CONTRIB_PER_COMPANY[company]['pulls'],
            CONTRIB_PER_COMPANY[company]['issues'],
            CONTRIB_PER_COMPANY[company]['reviews'],
            CONTRIB_PER_COMPANY[company]['comments'],
            CONTRIB_PER_COMPANY[company]['total']
        ))

    return
    

if __name__ == '__main__':
    main()
