import re
import os
import time
import json
import random
import string
import base64
import urllib
import requests
import brightid
import crypto_tools
import config

just_met_conns = {}


def init_brightid_bot():
    bot = brightid.tools.create_bright_id()
    with open(config.BOT_BRIGHTID_FILE, 'w') as f:
        f.write(json.dumps(bot))
    for tusted_conn in config.TUSTED_CONNS:
        connect_to(bot, tusted_conn, 'already known')


def load_brightid():
    if not os.path.exists(config.BOT_BRIGHTID_FILE):
        init_brightid_bot()
    with open(config.BOT_BRIGHTID_FILE, 'r') as f:
        return json.loads(f.read())


def connect_to(brightid_bot, target, level, report_reason=None):
    brightid_node = brightid.Node(config.BRIGHTID_NODE_URL)
    op = {
        'name': 'Connect',
        'id1': brightid_bot['id'],
        'id2': target,
        'level': level,
        'timestamp': int(time.time() * 1000),
        'v': 6
    }
    if report_reason:
        op['reportReason'] = report_reason
    op['sig1'] = brightid.tools.sign(op, brightid_bot['private'])
    op_hash = brightid_node.operations.post(op)
    print(
        f'connect to: {target}\tlevel: {level}\t{brightid_node.operations.get(op_hash)}')


def save_connection(profile_data):
    profile_dir = os.path.join(config.CONNECTIONS_DIR, profile_data['id'])
    if not os.path.isdir(profile_dir):
        os.makedirs(profile_dir)

    p = re.compile('data:image/(.*);base64')
    result = p.search(profile_data['photo'])
    if result:
        img_type = result.group(1)
        image_64_decode = base64.decodebytes(
            profile_data['photo'].replace(result.group(), '').encode())
    else:
        img_type = 'jpg'
        image_64_decode = base64.decodebytes(profile_data['photo'].encode())

    with open(f'{profile_dir}/{profile_data["name"]}.{img_type}', 'wb') as f:
        f.write(image_64_decode)

    with open(f'{profile_dir}/data.json', 'w') as f:
        f.write(json.dumps(profile_data))


def fetch_channel_profiles(brightid_bot, base_url, channel_id, aes_key):
    print(f'fetching profiles: {base_url}/list/{channel_id}')
    r = requests.get(f'{base_url}/list/{channel_id}',
                     headers={'Cache-Control': 'no-cache'})
    profile_ids = r.json()['profileIds']
    bot_connections = get_bot_connections(brightid_bot)
    for profile_id in profile_ids:
        if profile_id == 'channelInfo.json':
            continue
        r = requests.get(f'{base_url}/download/{channel_id}/{profile_id}',
                         headers={'Cache-Control': 'no-cache'})
        encrypted_profile_data = r.json()['data']
        profile_data = crypto_tools.decrypt(
            encrypted_profile_data, aes_key.encode())
        profile_data = json.loads(profile_data.decode('utf8'))
        if profile_data['id'] == brightid_bot['id'] or bot_connections.get(profile_data['id']) == 'reported':
            continue

        if bot_connections.get(profile_data['id']) == 'just met':
            just_met_conns[profile_data['id']] = time.time()
            continue

        save_connection(profile_data)
        connect_to(brightid_bot, profile_data['id'], 'just met')
        just_met_conns[profile_data['id']] = time.time()


def upload_profile_to_channel(brightid_bot, base_url, channel_id, aes_key):
    print(f'uploading bot profile: {base_url}/upload/{channel_id}')
    try:
        r = requests.get(config.RANDOM_USER_URL)
        random_profile_data = r.json()['results'][0]
        photo = base64.b64encode(requests.get(
            random_profile_data['picture']['medium']).content)
        photo = f'data:image/{random_profile_data["picture"]["medium"].split(".")[-1]};base64,' + photo.decode(
            'utf-8')
        name = random_profile_data['name']['first']
        if not os.path.exists(config.LOCAL_BOT_PROFILE):
            with open(config.LOCAL_BOT_PROFILE, 'w') as f:
                f.write(json.dumps({'photo': photo, 'name': name}))
    except:
        with open(config.LOCAL_BOT_PROFILE, 'r') as f:
            bot_profile = json.loads(f.read())
        photo = bot_profile.get('photo')
        name = bot_profile.get('name')
    profile_data = {
        'id': brightid_bot['id'],
        'photo': photo,
        'name': name,
        'socialMedia': [],
        'profileTimestamp': int(time.time() * 1000),
        'notificationToken': '',
        'version': 1,
    }
    encrypted = crypto_tools.encrypt(json.dumps(
        profile_data).encode(), aes_key.encode())
    profile_id = ''.join(random.choice(string.ascii_letters)
                         for i in range(12))
    r = requests.post(f'{base_url}/upload/{channel_id}', data={
                      'data': encrypted, 'uuid': profile_id}, headers={'Cache-Control': 'no-cache'})


def make_connection(connection_url, brightid_bot):
    connection_url = urllib.parse.unquote_plus(connection_url)
    parsed_url = urllib.parse.urlparse(connection_url)
    aes_key = urllib.parse.parse_qs(parsed_url.query)['aes'][0]
    base_url = parsed_url.path.replace('/connection-code/', '')
    channel_id = urllib.parse.parse_qs(parsed_url.query)['id'][0]
    r = requests.get(f'{base_url}/download/{channel_id}/channelInfo.json',
                     headers={'Cache-Control': 'no-cache'})
    channel = r.json().get('data')
    if not channel or channel['timestamp'] + channel['ttl'] - time.time() * 1000 < config.MIN_CHANNEL_JOIN_TTL:
        return
    try:
        upload_profile_to_channel(brightid_bot, base_url, channel_id, aes_key)
        fetch_channel_profiles(brightid_bot, base_url, channel_id, aes_key)
    except Exception as e:
        print('error in making connection: ', e)


def check_just_met_conns(brightid_bot):
    for conn in list(just_met_conns.keys()):
        r = requests.get(
            f'{config.BRIGHTID_NODE_URL}/users/{brightid_bot["id"]}/profile/{conn}').json()
        conn_level = r['data'].get('level', 'not connected')
        if conn_level in ['already known', 'recovery']:
            print('reporting...')
            connect_to(brightid_bot, conn, 'reported', 'spammer')
            del just_met_conns[conn]
        elif time.time() - just_met_conns[conn] > 24*60*60:
            del just_met_conns[conn]


def react_to_connection_requests(brightid_bot, connection_requests):
    for connection_request in list(connection_requests):
        make_connection(connection_request, brightid_bot)
        connection_requests.remove(connection_request)


def get_bot_connections(brightid_bot):
    connections = requests.get(
        f'{config.BRIGHTID_NODE_URL}/users/{brightid_bot["id"]}/connections/outbound').json()['data']['connections']
    return {c['id']: c['level'] for c in connections}
