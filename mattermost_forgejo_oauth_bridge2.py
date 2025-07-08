#!/usr/bin/env python3

import json
import os
import requests
import hmac
import hashlib
import base64
import urllib.parse
from flask import Flask, request, jsonify, redirect, session, url_for
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sqlite3
from functools import wraps
from loguru import logger

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')

# 設定
FORGEJO_URL = os.getenv('FORGEJO_URL', 'http://192.168.0.131:3000')
FORGEJO_CLIENT_ID = os.getenv('FORGEJO_CLIENT_ID', '')
FORGEJO_CLIENT_SECRET = os.getenv('FORGEJO_CLIENT_SECRET', '')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
MATTERMOST_TOKEN = os.getenv('MATTERMOST_TOKEN', '')
MATTERMOST_WEBHOOK_URL = os.getenv('MATTERMOST_WEBHOOK_URL', '')
MATTERMOST_API_URL = os.getenv('MATTERMOST_API_URL', '')
MATTERMOST_API_TOKEN = os.getenv('MATTERMOST_API_TOKEN', '')
BASE_URL = os.getenv('BASE_URL', 'http://localhost:5005')

# データベース初期化
def init_db():
    conn = sqlite3.connect('bridge.db')
    cursor = conn.cursor()
    
    # ユーザートークンテーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_tokens (
            mattermost_user_id TEXT PRIMARY KEY,
            mattermost_username TEXT,
            forgejo_access_token TEXT,
            forgejo_refresh_token TEXT,
            forgejo_username TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Issue-スレッドマッピングテーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS issue_thread_mapping (
            issue_key TEXT PRIMARY KEY,
            channel_id TEXT,
            mattermost_username TEXT,
            channel_name TEXT,
            team_domain TEXT,
            created_at TIMESTAMP,
            issue_url TEXT,
            root_message_id TEXT
        )
    ''')
    

    
    conn.commit()
    conn.close()

init_db()

class ForgejoOAuth2API:
    def __init__(self, base_url, client_id, client_secret):
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
    
    def get_auth_url(self, redirect_uri, state):
        """OAuth2認証URLを生成"""
        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'read:user,read:repository,write:repository,write:issue',
            'state': state
        }
        return f"{self.base_url}/login/oauth/authorize?" + urllib.parse.urlencode(params)
    
    def exchange_code_for_token(self, code, redirect_uri):
        """認証コードをアクセストークンに交換"""
        url = f"{self.base_url}/login/oauth/access_token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        
        headers = {'Accept': 'application/json'}
        
        try:
            response = requests.post(url, data=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to exchange code for token: {e}")
            return None

class ForgejoAPI:
    def __init__(self, base_url, access_token):
        self.base_url = base_url.rstrip('/')
        self.access_token = access_token
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_user_info(self):
        """ユーザー情報を取得"""
        url = f"{self.base_url}/api/v1/user"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get user info: {e}")
            return None
    
    def get_user_repos(self):
        """ユーザーがアクセスできるリポジトリ一覧を取得"""
        url = f"{self.base_url}/api/v1/user/repos"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get user repos: {e}")
            return None
    
    def check_repo_access(self, owner, repo):
        """特定リポジトリへのアクセス権限をチェック"""
        url = f"{self.base_url}/api/v1/repos/{owner}/{repo}"
        try:
            response = requests.get(url, headers=self.headers)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def create_issue(self, owner, repo, title, body):
        """Issue作成"""
        url = f"{self.base_url}/api/v1/repos/{owner}/{repo}/issues"
        data = {
            'title': title,
            'body': body
        }
        
        try:
            response = requests.post(url, json=data, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create issue: {e}")
            return None

class MattermostAPI:
    def __init__(self, api_url, token):
        self.api_url = api_url.rstrip('/')
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    
    def post_message(self, channel_id, message, root_id=None):
        """メッセージ投稿"""
        url = f"{self.api_url}/api/v4/posts"
        data = {
            'channel_id': channel_id,
            'message': message
        }
        
        if root_id:
            data['root_id'] = root_id
            
        try:
            response = requests.post(url, json=data, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to post message: {e}")
            return None

def get_user_token(mattermost_user_id):
    """DBからユーザートークンを取得"""
    conn = sqlite3.connect('bridge.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT forgejo_access_token, forgejo_username, expires_at 
        FROM user_tokens 
        WHERE mattermost_user_id = ?
    ''', (mattermost_user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        access_token, forgejo_username, expires_at = result
        # トークンの有効期限チェック（簡易版）
        return {
            'access_token': access_token,
            'forgejo_username': forgejo_username
        }
    return None

def save_user_token(mattermost_user_id, mattermost_username, token_data, forgejo_username):
    """ユーザートークンをDBに保存"""
    conn = sqlite3.connect('bridge.db')
    cursor = conn.cursor()
    
    expires_at = datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600))
    
    cursor.execute('''
        INSERT OR REPLACE INTO user_tokens 
        (mattermost_user_id, mattermost_username, forgejo_access_token, 
         forgejo_refresh_token, forgejo_username, expires_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (
        mattermost_user_id,
        mattermost_username,
        token_data.get('access_token'),
        token_data.get('refresh_token'),
        forgejo_username,
        expires_at
    ))
    
    conn.commit()
    conn.close()

def save_issue_thread_mapping(issue_key, channel_id, username, channel_name, 
                             team_domain, issue_url, root_message_id=None):
    """Issue-スレッドマッピングをDBに保存"""
    conn = sqlite3.connect('bridge.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO issue_thread_mapping 
        (issue_key, channel_id, mattermost_username, channel_name, 
         team_domain, created_at, issue_url, root_message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        issue_key, channel_id, username, channel_name,
        team_domain, datetime.now().isoformat(), issue_url, root_message_id
    ))
    
    conn.commit()
    conn.close()

def get_issue_thread_mapping(issue_key):
    """Issue-スレッドマッピングを取得"""
    conn = sqlite3.connect('bridge.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT channel_id, mattermost_username, channel_name, team_domain, 
               created_at, issue_url, root_message_id
        FROM issue_thread_mapping 
        WHERE issue_key = ?
    ''', (issue_key,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'channel_id': result[0],
            'username': result[1],
            'channel_name': result[2],
            'team_domain': result[3],
            'created_at': result[4],
            'issue_url': result[5],
            'root_message_id': result[6]
        }
    return None

@app.route('/', methods=['GET'])
def root():
    """ルートエンドポイント"""
    return jsonify({
        'message': 'Mattermost-Forgejo OAuth2 Bridge Server',
        'status': 'running',
        'endpoints': ['/webhook', '/auth/connect', '/auth/callback', '/health', '/debug']
    })

@app.route('/auth/connect', methods=['GET'])
def connect_oauth():
    """OAuth2認証開始"""
    # Mattermostからのリダイレクト時にユーザー情報を取得
    mattermost_user_id = request.args.get('user_id')
    mattermost_username = request.args.get('username')
    
    if not mattermost_user_id or not mattermost_username:
        return jsonify({'error': 'Missing user information'}), 400
    
    # セッションに保存
    session['mattermost_user_id'] = mattermost_user_id
    session['mattermost_username'] = mattermost_username
    
    # OAuth2フロー開始
    oauth = ForgejoOAuth2API(FORGEJO_URL, FORGEJO_CLIENT_ID, FORGEJO_CLIENT_SECRET)
    redirect_uri = url_for('oauth_callback', _external=True)
    state = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8')
    session['oauth_state'] = state
    
    auth_url = oauth.get_auth_url(redirect_uri, state)
    return redirect(auth_url)

@app.route('/auth/callback', methods=['GET'])
def oauth_callback():
    """OAuth2コールバック"""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        return jsonify({'error': f'OAuth error: {error}'}), 400
    
    if not code or not state:
        return jsonify({'error': 'Missing code or state'}), 400
    
    # CSRF攻撃防止
    if state != session.get('oauth_state'):
        return jsonify({'error': 'Invalid state parameter'}), 400
    
    # アクセストークンを取得
    oauth = ForgejoOAuth2API(FORGEJO_URL, FORGEJO_CLIENT_ID, FORGEJO_CLIENT_SECRET)
    redirect_uri = url_for('oauth_callback', _external=True)
    token_data = oauth.exchange_code_for_token(code, redirect_uri)
    
    if not token_data:
        return jsonify({'error': 'Failed to exchange code for token'}), 500
    
    # Forgejoのユーザー情報を取得
    forgejo_api = ForgejoAPI(FORGEJO_URL, token_data['access_token'])
    user_info = forgejo_api.get_user_info()
    
    if not user_info:
        return jsonify({'error': 'Failed to get user info'}), 500
    
    # トークンを保存
    mattermost_user_id = session.get('mattermost_user_id')
    mattermost_username = session.get('mattermost_username')
    
    save_user_token(
        mattermost_user_id,
        mattermost_username,
        token_data,
        user_info['login']
    )
    
    # セッションクリア
    session.clear()
    
    return jsonify({
        'message': 'Successfully connected to Forgejo!',
        'forgejo_username': user_info['login'],
        'mattermost_username': mattermost_username
    })

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Webhook エンドポイント"""
    logger.info(f"=== INCOMING REQUEST ===")
    logger.info(f"Method: {request.method}")
    logger.info(f"Content-Type: {request.content_type}")
    logger.info(f"========================")
    
    # Mattermostのスラッシュコマンド処理
    if request.content_type == 'application/x-www-form-urlencoded':
        data = request.form.to_dict()
        
        # トークン検証
        token = data.get('token', '')
        if MATTERMOST_TOKEN and token != MATTERMOST_TOKEN:
            logger.error("Invalid token received")
            return jsonify({
                'response_type': 'ephemeral',
                'text': '❌ Invalid token'
            }), 401
        
        return handle_slash_command(data)
    
    # Forgejo Webhook処理
    elif request.is_json:
        request_body = request.get_data()
        
        # Webhook検証
        if not verify_forgejo_webhook(request.headers, request_body):
            logger.error("Invalid Forgejo webhook secret")
            return jsonify({'error': 'Invalid webhook secret'}), 401
        
        data = request.get_json()
        return handle_forgejo_webhook(data)
    
    else:
        return jsonify({'error': 'Unsupported content type'}), 400

def handle_slash_command(data):
    """Mattermostスラッシュコマンドの処理"""
    try:
        text = data.get('text', '').strip()
        user_id = data.get('user_id', '')
        username = data.get('user_name', 'Unknown')
        channel_name = data.get('channel_name', 'Unknown')
        channel_id = data.get('channel_id', '')
        team_domain = data.get('team_domain', '')
        
        logger.info(f"Processing slash command from user: {username} (ID: {user_id})")
        
        # OAuth2認証チェック
        user_token = get_user_token(user_id)
        if not user_token:
            connect_url = f"{BASE_URL}/auth/connect?user_id={user_id}&username={username}"
            return jsonify({
                'response_type': 'ephemeral',
                'text': f'🔐 **Authentication Required**\n\nPlease connect your Forgejo account first:\n{connect_url}\n\nAfter connecting, you can use the `/issue` command.'
            })
        
        # ヘルプまたは空のコマンド
        if not text:
            return jsonify({
                'response_type': 'ephemeral',
                'text': f'''**Usage**: `/issue <owner> <repo> <title> [body]`

**One-command Issue Creation:**
You can create an issue with detailed description in a single command:

**Connected as**: {user_token['forgejo_username']}

**Example:**
```
/issue myorg myrepo "Add authentication feature"

## Description
We need to implement user authentication with the following requirements:

### Features needed:
- Login/logout functionality
- Password reset
- Session management

### Code example:
\`\`\`python
def authenticate_user(username, password):
    # Implementation here
    return validate_credentials(username, password)
\`\`\`

### Additional notes:
- Should integrate with existing user database
- Need to add proper error handling
```'''
            })
        
        # テキストを行ごとに分割してパース
        lines = text.split('\n')
        first_line = lines[0].strip()
        
        # 最初の行から owner, repo, title を抽出
        parts = first_line.split(' ', 2)
        if len(parts) < 3:
            return jsonify({
                'response_type': 'ephemeral',
                'text': '❌ **Error**: Please provide all required parameters.\n\nUsage: `/issue <owner> <repo> <title> [detailed_body]`\n\nExample:\n```\n/issue myorg myrepo "Bug fix"\n\nDetailed description here...\n```'
            })
        
        owner, repo, title = parts
        title = title.strip('"\'')
        
        # 残りの行をbodyとして使用
        body_lines = lines[1:] if len(lines) > 1 else []
        user_body = '\n'.join(body_lines).strip()
        
        # 権限チェック
        forgejo_api = ForgejoAPI(FORGEJO_URL, user_token['access_token'])
        if not forgejo_api.check_repo_access(owner, repo):
            return jsonify({
                'response_type': 'ephemeral',
                'text': f'❌ **Access Denied**\n\nYou don\'t have access to repository `{owner}/{repo}`.\n\nConnected as: {user_token["forgejo_username"]}'
            })
        
        # Issue本文を作成
        body = f"## Issue created from Mattermost\n\n"
        body += f"**Channel:** {channel_name}\n"
        body += f"**Team:** {team_domain}\n" 
        body += f"**Created by:** @{username} (Forgejo: @{user_token['forgejo_username']})\n"
        body += f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        body += f"---\n\n"
        
        if user_body:
            body += user_body
        else:
            body += f"**Description:**\n{title}"
        
        # Issue作成
        issue = forgejo_api.create_issue(owner, repo, title, body)
        
        if issue:
            logger.info(f"Created issue #{issue['number']}: {title}")
            
            response_text = f'✅ **Issue Created Successfully!**\n\n**Title:** {title}\n**Repository:** {owner}/{repo}\n**Issue #{issue["number"]}:** {issue["html_url"]}\n**Created as:** {user_token["forgejo_username"]}\n\n*This thread will receive updates when the issue is updated.*'
            
            # Mattermostにメッセージを投稿
            root_message_id = None
            if MATTERMOST_API_URL and MATTERMOST_API_TOKEN:
                mattermost = MattermostAPI(MATTERMOST_API_URL, MATTERMOST_API_TOKEN)
                post_result = mattermost.post_message(channel_id, response_text)
                if post_result:
                    root_message_id = post_result.get('id')
            
            # Issue-スレッドマッピングを保存
            issue_key = f"{owner}/{repo}#{issue['number']}"
            save_issue_thread_mapping(
                issue_key, channel_id, username, channel_name,
                team_domain, issue['html_url'], root_message_id
            )
            
            if root_message_id:
                return jsonify({'text': ''}), 200
            else:
                return jsonify({
                    'response_type': 'in_channel',
                    'text': response_text
                })
        else:
            return jsonify({
                'response_type': 'ephemeral',
                'text': '❌ **Failed to create issue**\n\nPlease check your permissions and try again.'
            })
            
    except Exception as e:
        logger.error(f"Error processing slash command: {e}")
        return jsonify({
            'response_type': 'ephemeral',
            'text': f'❌ **Internal Error:** {str(e)}'
        })

def verify_forgejo_webhook(request_headers, request_body):
    """Forgejoからのwebhookを検証"""
    if not WEBHOOK_SECRET:
        return True
    
    signature_header = request_headers.get('X-Hub-Signature-256')
    if not signature_header:
        return False
    
    if not signature_header.startswith('sha256='):
        return False
    
    received_signature = signature_header[7:]
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(received_signature, expected_signature)

def handle_forgejo_webhook(data):
    """Forgejoからのwebhookイベントを処理"""
    try:
        action = data.get('action', '')
        
        if 'comment' in data and 'issue' in data:
            return handle_issue_comment_event(data, action)
        elif 'issue' in data:
            return handle_issue_event(data, action)
        elif 'pull_request' in data:
            return handle_pull_request_event(data, action)
        else:
            return jsonify({'status': 'ignored'}), 200
            
    except Exception as e:
        logger.error(f"Error processing Forgejo webhook: {e}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_issue_comment_event(data, action):
    """Issue commentイベントの処理"""
    issue = data.get('issue', {})
    comment = data.get('comment', {})
    repository = data.get('repository', {})
    sender = data.get('sender', {})
    
    owner = repository.get('owner', {}).get('login', '')
    repo_name = repository.get('name', '')
    issue_number = issue.get('number', '')
    issue_title = issue.get('title', '')
    sender_name = sender.get('login', 'Unknown')
    
    comment_body = comment.get('body', '')
    comment_url = comment.get('html_url', '')
    
    issue_key = f"{owner}/{repo_name}#{issue_number}"
    thread_info = get_issue_thread_mapping(issue_key)
    
    message = f"💬 **New Comment on Issue**\n\n**Repository:** {owner}/{repo_name}\n**Issue #{issue_number}:** {issue_title}\n**Comment by:** @{sender_name}\n\n**Comment:**\n{comment_body}\n\n**URL:** {comment_url}"
    
    if thread_info and MATTERMOST_API_URL and MATTERMOST_API_TOKEN:
        mattermost = MattermostAPI(MATTERMOST_API_URL, MATTERMOST_API_TOKEN)
        root_id = thread_info.get('root_message_id')
        
        if root_id:
            mattermost.post_message(thread_info['channel_id'], message, root_id=root_id)
        else:
            mattermost.post_message(thread_info['channel_id'], message)
    
    return jsonify({'status': 'processed'}), 200

def handle_issue_event(data, action):
    """Issue関連イベントの処理"""
    issue = data.get('issue', {})
    repository = data.get('repository', {})
    sender = data.get('sender', {})
    
    owner = repository.get('owner', {}).get('login', '')
    repo_name = repository.get('name', '')
    issue_number = issue.get('number', '')
    issue_title = issue.get('title', '')
    issue_url = issue.get('html_url', '')
    sender_name = sender.get('login', 'Unknown')
    
    issue_key = f"{owner}/{repo_name}#{issue_number}"
    thread_info = get_issue_thread_mapping(issue_key)
    
    message = ""
    
    if action == 'closed':
        message = f"✅ **Issue Closed**\n\n**Repository:** {owner}/{repo_name}\n**Issue #{issue_number}:** {issue_title}\n**Closed by:** @{sender_name}\n**URL:** {issue_url}"
    elif action == 'reopened':
        message = f"🔄 **Issue Reopened**\n\n**Repository:** {owner}/{repo_name}\n**Issue #{issue_number}:** {issue_title}\n**Reopened by:** @{sender_name}\n**URL:** {issue_url}"
    
    if message and thread_info and MATTERMOST_API_URL and MATTERMOST_API_TOKEN:
        mattermost = MattermostAPI(MATTERMOST_API_URL, MATTERMOST_API_TOKEN)
        root_id = thread_info.get('root_message_id')
        
        if root_id:
            mattermost.post_message(thread_info['channel_id'], message, root_id=root_id)
        else:
            mattermost.post_message(thread_info['channel_id'], message)
    
    return jsonify({'status': 'processed'}), 200

def handle_pull_request_event(data, action):
    """Pull Request関連イベントの処理"""
    # 既存のPR処理ロジックをそのまま使用
    return jsonify({'status': 'processed'}), 200

@app.route('/health', methods=['GET'])
def health():
    """ヘルスチェック"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '3.2.0-single-command',
        'oauth2_configured': bool(FORGEJO_CLIENT_ID and FORGEJO_CLIENT_SECRET)
    })

if __name__ == '__main__':
    if not FORGEJO_CLIENT_ID or not FORGEJO_CLIENT_SECRET:
        logger.error("FORGEJO_CLIENT_ID and FORGEJO_CLIENT_SECRET environment variables are required")
        exit(1)
    
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting OAuth2 bridge server with single-command support on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
