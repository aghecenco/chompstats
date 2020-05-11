import boto3
from boto3.dynamodb.conditions import Key
import datetime
from dateutil.parser import parse
import decimal
import json
import os

# DynamoDB identifiers
ISSUES_TABLE_NAME = 'FoobarIssues'
PULLS_TABLE_NAME = 'FoobarPulls'

SQS = 'https://sqs.us-west-2.amazonaws.com/948479086345/GithubIssueClosedEvents.fifo'

TODAY = datetime.datetime.now()


# Helper class to convert a DynamoDB item to JSON.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)


def days_delta(start, end):
    return (end - start.replace(tzinfo=end.tzinfo)).days


def mark_issue_dropped(issue, issues_table):
    print('issue {} will be dropped'.format(issue['number']))
    _ = issues_table.update_item(
        Key={ 'number': '{}'.format(issue['number']) },
        UpdateExpression="set age=:a, #s=:s, closed_at=:c",
        ExpressionAttributeValues={
            ':a': days_delta(parse(issue['created_at']), parse(issue['closed_at'])),
            ':s': 'dropped',
            ':c': issue['closed_at']
        },
        ExpressionAttributeNames={ "#s": "state" },
        ReturnValues="UPDATED_NEW"
    )


def delete_sqs_msg(sqs, message):
    try:
        sqs.delete_message(
            QueueUrl=SQS,
            ReceiptHandle=message['ReceiptHandle']
        )
    except Exception:
        pass


def update_closed_issues(issues_table):
    sqs = boto3.client('sqs', 'us-west-2')

    while True:
        resp = sqs.receive_message(
            QueueUrl=SQS,
            AttributeNames=['All'],
            MaxNumberOfMessages=1
        )
        try:
            messages = resp['Messages']
        except KeyError:
            break

        message = messages[0]
        issue = json.loads(message['Body'])

        response = issues_table.query(
            KeyConditionExpression=Key('number').eq('{}'.format(issue['number']))
        )
        db_issue = response['Items'][0]
        if db_issue['state'] == 'open':
            # No PR has closed this in the meantime. Mark dropped.  
            mark_issue_dropped(issue, issues_table)
        
        delete_sqs_msg(sqs, message)


def item_type(item):
    return 'issue' if '/issues/' in item['url'] else 'pr'


def age_up_items(table):
    response = table.scan(
        FilterExpression=Key('state').eq('open') & Key('answered').eq(False)
    )
    for open_it in response['Items']:
        age = days_delta(parse(open_it['created_at']), TODAY)
        print('{} {} will be aged up to {}'.format(
            item_type(open_it), open_it['number'], age
        ))
        _ = table.update_item(
            Key={'number': open_it['number']},
            UpdateExpression="set unanswered_age=:u, age=:a",
            ExpressionAttributeValues={
                ':a': age,
                ':u': age,
            },
            ReturnValues="UPDATED_NEW"
        )


def main():
    dynamodb = boto3.resource(
        'dynamodb', 
        region_name='us-west-2', 
        endpoint_url="https://dynamodb.us-west-2.amazonaws.com"
    )
    issues_table = dynamodb.Table(ISSUES_TABLE_NAME)
    pulls_table = dynamodb.Table(PULLS_TABLE_NAME)

    update_closed_issues(issues_table)
    age_up_items(issues_table)
    age_up_items(pulls_table)


if __name__ == '__main__':
    main()
