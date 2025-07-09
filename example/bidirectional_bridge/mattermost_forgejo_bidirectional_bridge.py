#!/usr/bin/env python3

import json
import logging
import os
import requests
import hmac
import hashlib
from flask import Flask, request, jsonify
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

FORGEJO_URL = os.getenv('FORGEJO_URL', 'http://192.168.0.131:3000')
FORGEJO_TOKEN = os.getenv('FORGEJO_TOKEN', '')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
MATTERMOST_TOKEN = os.getenv('MATTERMOST_TOKEN', '')
MATTERMOST_WEBHOOK_URL = os.getenv('MATTERMOST_WEBHOOK_URL', '')  # 新規追加
MATTERMOST_API_URL = os.getenv('MATTERMOST_API_URL', '')  # 新規追加
MATTERMOST_API_TOKEN = os.getenv('MATTERMOST_API_TOKEN', '')  # 新規追加

# スレッド情報を保存するための簡易データベース（実際の運用では永続化が必要）
issue_thread_mapping = {}

class ForgejoAPI:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.headers = {
            'Authorization': f'token {token}',
            'Content-Type': 'application/json'
        }
    
    def create_issue(self, owner, repo, title, body):
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
        """チャンネルまたはスレッドにメッセージを投稿"""
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

def send_webhook_notification(message, channel=None, username="Forgejo Bot", icon_url="https://forgejo.org/favicon.ico"):
    """Mattermost Incoming Webhookを使用してメッセージを送信"""
    if not MATTERMOST_WEBHOOK_URL:
        logger.warning("MATTERMOST_WEBHOOK_URL not configured")
        return False
    
    payload = {
        'text': message,
        'username': username,
        'icon_url': icon_url
    }
    
    if channel:
        payload['channel'] = channel
    
    try:
        response = requests.post(MATTERMOST_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send webhook notification: {e}")
        return False

def verify_token(request_token):
    """Mattermostから送信されたトークンを検証"""
    if MATTERMOST_TOKEN and request_token != MATTERMOST_TOKEN:
        return False
    return True

def verify_forgejo_webhook(request_headers, request_body):
    """Forgejoからのwebhookを検証"""
    if not WEBHOOK_SECRET:
        return True  # シークレットが設定されていない場合はスキップ
    
    # GitHub/Forgejo形式の署名を確認
    signature_header = request_headers.get('X-Hub-Signature-256')
    if not signature_header:
        logger.warning("No X-Hub-Signature-256 header found")
        return False
    
    # 署名をパース (sha256=<hash> 形式)
    if not signature_header.startswith('sha256='):
        logger.warning(f"Invalid signature format: {signature_header}")
        return False
    
    received_signature = signature_header[7:]  # 'sha256=' を除去
    
    # 期待される署名を計算
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    
    # 署名を比較
    is_valid = hmac.compare_digest(received_signature, expected_signature)
    
    if not is_valid:
        logger.error(f"Webhook signature mismatch. Expected: {expected_signature}, Received: {received_signature}")
    else:
        logger.info("Webhook signature verified successfully")
    
    return is_valid

@app.route('/', methods=['GET', 'POST'])
def root():
    """ルートエンドポイント - 接続テスト用"""
    logger.info("Root endpoint accessed")
    return jsonify({
        'message': 'Mattermost-Forgejo Bridge Server',
        'status': 'running',
        'endpoints': ['/webhook', '/health', '/debug']
    })

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    logger.info(f"=== INCOMING REQUEST ===")
    logger.info(f"Method: {request.method}")
    logger.info(f"URL: {request.url}")
    logger.info(f"Remote IP: {request.remote_addr}")
    logger.info(f"Headers: {dict(request.headers)}")
    logger.info(f"Content-Type: {request.content_type}")
    logger.info(f"Raw data: {request.get_data()}")
    logger.info(f"========================")
    
    # Mattermostのスラッシュコマンド処理
    if request.content_type == 'application/x-www-form-urlencoded':
        data = request.form.to_dict()
        logger.info(f"Form data: {data}")
        
        # トークン検証
        token = data.get('token', '')
        if not verify_token(token):
            logger.error("Invalid token received")
            return jsonify({
                'response_type': 'ephemeral',
                'text': '❌ Invalid token'
            }), 401
        
        return handle_slash_command(data)
    
    # Forgejo Webhook処理
    elif request.is_json:
        # リクエストボディを取得（署名検証のため）
        request_body = request.get_data()
        
        # Forgejo webhookの検証
        if not verify_forgejo_webhook(request.headers, request_body):
            logger.error("Invalid Forgejo webhook secret")
            return jsonify({'error': 'Invalid webhook secret'}), 401
        
        data = request.get_json()
        logger.info(f"JSON data: {data}")
        
        # Forgejoイベントの処理
        return handle_forgejo_webhook(data)
    
    else:
        return jsonify({'error': 'Unsupported content type'}), 400

def handle_slash_command(data):
    """Mattermostスラッシュコマンドの処理"""
    try:
        text = data.get('text', '').strip()
        username = data.get('user_name', 'Unknown')
        channel_name = data.get('channel_name', 'Unknown')
        channel_id = data.get('channel_id', '')
        team_domain = data.get('team_domain', '')
        
        logger.info(f"Processing slash command: {text} from user: {username}")
        
        # ヘルプまたは空のコマンド
        if not text:
            return jsonify({
                'response_type': 'ephemeral',
                'text': '''**Usage**: `/issue <owner> <repo> <title>`
                
**Example**: `/issue myorg myrepo "Fix login bug"`

**Parameters**:
- `owner`: Repository owner/organization name
- `repo`: Repository name  
- `title`: Issue title (use quotes if it contains spaces)'''
            })
        
        # テキストをパース
        parts = text.split(' ', 2)
        if len(parts) < 3:
            return jsonify({
                'response_type': 'ephemeral',
                'text': '❌ **Error**: Please provide all required parameters.\n\nUsage: `/issue <owner> <repo> <title>`'
            })
        
        owner, repo, title = parts
        
        # タイトルのクォート処理
        title = title.strip('"\'')
        
        # Issue本文を作成
        body = f"## Issue created from Mattermost\n\n"
        body += f"**Channel:** {channel_name}\n"
        body += f"**Team:** {team_domain}\n" 
        body += f"**Created by:** @{username}\n"
        body += f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        body += f"**Original Request:** `{text}`\n\n"
        body += f"---\n\n"
        body += f"**Description:**\n{title}"
        
        # Forgejo APIでIssueを作成
        forgejo = ForgejoAPI(FORGEJO_URL, FORGEJO_TOKEN)
        issue = forgejo.create_issue(owner, repo, title, body)
        
        if issue:
            logger.info(f"Created issue #{issue['number']}: {title}")
            
            # Mattermostに応答を送信し、そのメッセージIDを取得
            response_text = f'✅ **Issue Created Successfully!**\n\n**Title:** {title}\n**Repository:** {owner}/{repo}\n**Issue #{issue["number"]}:** {issue["html_url"]}\n\n*This thread will receive updates when the issue is updated.*'
            
            # もしMattermost APIが利用可能なら、メッセージを投稿してIDを取得
            root_message_id = None
            if MATTERMOST_API_URL and MATTERMOST_API_TOKEN:
                mattermost = MattermostAPI(MATTERMOST_API_URL, MATTERMOST_API_TOKEN)
                post_result = mattermost.post_message(channel_id, response_text)
                if post_result:
                    root_message_id = post_result.get('id')
                    logger.info(f"Created root message with ID: {root_message_id}")
            
            # issueとスレッドの関連付けを保存
            issue_key = f"{owner}/{repo}#{issue['number']}"
            issue_thread_mapping[issue_key] = {
                'channel_id': channel_id,
                'username': username,
                'channel_name': channel_name,
                'team_domain': team_domain,
                'created_at': datetime.now().isoformat(),
                'issue_url': issue['html_url'],
                'root_message_id': root_message_id  # 新規追加
            }
            
            logger.info(f"Saved thread mapping for {issue_key} with root_id: {root_message_id}")
            
            # API経由でメッセージを投稿した場合は、空のレスポンスを返す
            if root_message_id:
                return jsonify({'text': ''}), 200
            else:
                # API投稿に失敗した場合は、従来通りSlash Command応答で投稿
                return jsonify({
                    'response_type': 'in_channel',
                    'text': response_text,
                    'username': 'Forgejo Bot',
                    'icon_url': 'https://forgejo.org/favicon.ico'
                })
        else:
            logger.error("Failed to create issue")
            return jsonify({
                'response_type': 'ephemeral',
                'text': '❌ **Failed to create issue**\n\nPossible causes:\n- Invalid repository owner/name\n- Insufficient permissions\n- Forgejo server connection issues\n\nPlease check the server logs for more details.'
            })
            
    except Exception as e:
        logger.error(f"Error processing slash command: {e}")
        return jsonify({
            'response_type': 'ephemeral',
            'text': f'❌ **Internal Error:** {str(e)}\n\nPlease contact the administrator.'
        })

def handle_forgejo_webhook(data):
    """Forgejoからのwebhookイベントを処理"""
    try:
        # イベントタイプの判定
        action = data.get('action', '')
        
        # issue_commentイベントの特別処理
        if 'comment' in data and 'issue' in data:
            return handle_issue_comment_event(data, action)
        elif 'issue' in data:
            return handle_issue_event(data, action)
        elif 'pull_request' in data:
            return handle_pull_request_event(data, action)
        else:
            logger.info(f"Unhandled webhook event: {action}")
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
    issue_url = issue.get('html_url', '')
    sender_name = sender.get('login', 'Unknown')
    
    comment_body = comment.get('body', '')
    comment_url = comment.get('html_url', '')
    
    issue_key = f"{owner}/{repo_name}#{issue_number}"
    
    # スレッド情報の取得
    thread_info = issue_thread_mapping.get(issue_key)
    
    message = f"💬 **New Comment on Issue**\n\n**Repository:** {owner}/{repo_name}\n**Issue #{issue_number}:** {issue_title}\n**Comment by:** @{sender_name}\n\n**Comment:**\n{comment_body}\n\n**URL:** {comment_url}"
    
    # メッセージの送信
    if thread_info and MATTERMOST_API_URL and MATTERMOST_API_TOKEN:
        # 元のスレッドに返信
        mattermost = MattermostAPI(MATTERMOST_API_URL, MATTERMOST_API_TOKEN)
        root_id = thread_info.get('root_message_id')
        
        if root_id:
            # スレッドとして返信
            result = mattermost.post_message(thread_info['channel_id'], message, root_id=root_id)
            if result:
                logger.info(f"Posted thread reply for {issue_key} to root message {root_id}")
            else:
                logger.error(f"Failed to post thread reply for {issue_key}")
        else:
            # root_message_idがない場合は通常のメッセージとして投稿
            result = mattermost.post_message(thread_info['channel_id'], message)
            if result:
                logger.info(f"Posted message for {issue_key} (no root_id available)")
            else:
                logger.error(f"Failed to post message for {issue_key}")
    else:
        # 通常の通知
        success = send_webhook_notification(message)
        if success:
            logger.info(f"Sent webhook notification for {issue_key}")
        else:
            logger.error(f"Failed to send webhook notification for {issue_key}")
    
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
    
    # スレッド情報の取得
    thread_info = issue_thread_mapping.get(issue_key)
    
    message = ""
    
    if action == 'opened':
        # 外部からissueが作成された場合（Mattermostからではない）
        if not thread_info:
            message = f"🆕 **New Issue Created**\n\n**Repository:** {owner}/{repo_name}\n**Issue #{issue_number}:** {issue_title}\n**Created by:** @{sender_name}\n**URL:** {issue_url}"
            send_webhook_notification(message)
        return jsonify({'status': 'processed'}), 200
    
    elif action == 'closed':
        if issue.get('state') == 'closed':
            message = f"✅ **Issue Closed**\n\n**Repository:** {owner}/{repo_name}\n**Issue #{issue_number}:** {issue_title}\n**Closed by:** @{sender_name}\n**URL:** {issue_url}"
    
    elif action == 'reopened':
        message = f"🔄 **Issue Reopened**\n\n**Repository:** {owner}/{repo_name}\n**Issue #{issue_number}:** {issue_title}\n**Reopened by:** @{sender_name}\n**URL:** {issue_url}"
    
    # メッセージがある場合の処理
    if message:
        if thread_info and MATTERMOST_API_URL and MATTERMOST_API_TOKEN:
            # 元のスレッドに返信
            mattermost = MattermostAPI(MATTERMOST_API_URL, MATTERMOST_API_TOKEN)
            root_id = thread_info.get('root_message_id')
            
            if root_id:
                # スレッドとして返信
                result = mattermost.post_message(thread_info['channel_id'], message, root_id=root_id)
                if result:
                    logger.info(f"Posted thread reply for {issue_key} to root message {root_id}")
                else:
                    logger.error(f"Failed to post thread reply for {issue_key}")
            else:
                # root_message_idがない場合は通常のメッセージとして投稿
                result = mattermost.post_message(thread_info['channel_id'], message)
                if result:
                    logger.info(f"Posted message for {issue_key} (no root_id available)")
                else:
                    logger.error(f"Failed to post message for {issue_key}")
        else:
            # 通常の通知
            success = send_webhook_notification(message)
            if success:
                logger.info(f"Sent webhook notification for {issue_key}")
            else:
                logger.error(f"Failed to send webhook notification for {issue_key}")
    
    return jsonify({'status': 'processed'}), 200

def handle_pull_request_event(data, action):
    """Pull Request関連イベントの処理"""
    pull_request = data.get('pull_request', {})
    repository = data.get('repository', {})
    sender = data.get('sender', {})
    
    owner = repository.get('owner', {}).get('login', '')
    repo_name = repository.get('name', '')
    pr_number = pull_request.get('number', '')
    pr_title = pull_request.get('title', '')
    pr_url = pull_request.get('html_url', '')
    sender_name = sender.get('login', 'Unknown')
    
    message = ""
    
    if action == 'opened':
        message = f"🔄 **New Pull Request**\n\n**Repository:** {owner}/{repo_name}\n**PR #{pr_number}:** {pr_title}\n**Created by:** @{sender_name}\n**URL:** {pr_url}"
    
    elif action == 'closed':
        if pull_request.get('merged', False):
            message = f"✅ **Pull Request Merged**\n\n**Repository:** {owner}/{repo_name}\n**PR #{pr_number}:** {pr_title}\n**Merged by:** @{sender_name}\n**URL:** {pr_url}"
        else:
            message = f"❌ **Pull Request Closed**\n\n**Repository:** {owner}/{repo_name}\n**PR #{pr_number}:** {pr_title}\n**Closed by:** @{sender_name}\n**URL:** {pr_url}"
    
    if message:
        success = send_webhook_notification(message)
        if success:
            logger.info(f"Sent PR notification for {owner}/{repo_name}#{pr_number}")
        else:
            logger.error(f"Failed to send PR notification for {owner}/{repo_name}#{pr_number}")
    
    return jsonify({'status': 'processed'}), 200

@app.route('/health', methods=['GET'])
def health():
    """ヘルスチェックエンドポイント"""
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'version': '2.0.0',
        'forgejo_url': FORGEJO_URL.replace('//', '//***:***@') if FORGEJO_TOKEN else FORGEJO_URL,
        'mattermost_webhook_configured': bool(MATTERMOST_WEBHOOK_URL),
        'mattermost_api_configured': bool(MATTERMOST_API_URL and MATTERMOST_API_TOKEN)
    })

@app.route('/debug', methods=['GET', 'POST'])
def debug_endpoint():
    """デバッグ用エンドポイント"""
    logger.info("Debug endpoint called")
    
    debug_info = {
        'method': request.method,
        'url': request.url,
        'remote_addr': request.remote_addr,
        'content_type': request.content_type,
        'headers': dict(request.headers),
        'args': dict(request.args),
        'form': dict(request.form),
        'json': request.get_json(silent=True),
        'data': request.get_data().decode('utf-8', errors='ignore'),
        'issue_thread_mapping': issue_thread_mapping
    }
    
    logger.info(f"Debug info: {debug_info}")
    
    return jsonify({
        'message': 'Debug endpoint response',
        'received_data': debug_info,
        'server_config': {
            'forgejo_url': FORGEJO_URL,
            'has_forgejo_token': bool(FORGEJO_TOKEN),
            'has_mattermost_token': bool(MATTERMOST_TOKEN),
            'has_mattermost_webhook_url': bool(MATTERMOST_WEBHOOK_URL),
            'has_mattermost_api_url': bool(MATTERMOST_API_URL),
            'has_mattermost_api_token': bool(MATTERMOST_API_TOKEN)
        }
    })

if __name__ == '__main__':
    if not FORGEJO_TOKEN:
        logger.error("FORGEJO_TOKEN environment variable is required")
        exit(1)
    
    if not MATTERMOST_TOKEN:
        logger.warning("MATTERMOST_TOKEN not set - token verification disabled")
    
    if not MATTERMOST_WEBHOOK_URL:
        logger.warning("MATTERMOST_WEBHOOK_URL not set - webhook notifications disabled")
    
    if not MATTERMOST_API_URL or not MATTERMOST_API_TOKEN:
        logger.warning("MATTERMOST_API_URL or MATTERMOST_API_TOKEN not set - thread replies disabled")
    
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting server on port {port}")
    logger.info(f"Forgejo URL: {FORGEJO_URL}")
    logger.info(f"Debug mode: {debug}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
