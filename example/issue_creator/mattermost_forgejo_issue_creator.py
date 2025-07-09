#!/usr/bin/env python3

import json
import logging
import os
import requests
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
MATTERMOST_TOKEN = os.getenv('MATTERMOST_TOKEN', '')  # 追加: Mattermostから取得したトークン

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

def verify_token(request_token):
    """Mattermostから送信されたトークンを検証"""
    if MATTERMOST_TOKEN and request_token != MATTERMOST_TOKEN:
        return False
    return True

@app.route('/', methods=['GET', 'POST'])
def root():
    """ルートエンドポイント - 接続テスト用"""
    logger.info("Root endpoint accessed")
    return jsonify({
        'message': 'Mattermost-Forgejo Bridge Server',
        'status': 'running',
        'endpoints': ['/webhook', '/health', '/test']
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
    
    # Mattermostのスラッシュコマンドは application/x-www-form-urlencoded で送信される
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
    
    # WebHook用の処理（既存のコード）
    elif request.is_json:
        data = request.get_json()
        logger.info(f"JSON data: {data}")
        
        if WEBHOOK_SECRET and request.headers.get('X-Webhook-Token') != WEBHOOK_SECRET:
            return jsonify({'error': 'Invalid webhook secret'}), 401
        
        if data.get('event') == 'post':
            return handle_post_event(data)
        
        return jsonify({'status': 'ignored'}), 200
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
            return jsonify({
                'response_type': 'in_channel',
                'text': f'✅ **Issue Created Successfully!**\n\n**Title:** {title}\n**Repository:** {owner}/{repo}\n**Issue #{issue["number"]}:** {issue["html_url"]}',
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

def handle_post_event(data):
    """WebHook投稿イベントの処理（既存機能）"""
    try:
        post = data.get('data', {}).get('post', {})
        message = post.get('message', '')
        username = data.get('data', {}).get('sender_name', 'Unknown')
        channel_name = data.get('data', {}).get('channel_name', 'Unknown')
        
        if not message.startswith('/issue'):
            return jsonify({'status': 'ignored'}), 200
        
        parts = message.split(' ', 3)
        if len(parts) < 4:
            return jsonify({'error': 'Usage: /issue <owner> <repo> <title>'}), 400
        
        _, owner, repo, title = parts
        
        body = f"Issue created from Mattermost\n\n"
        body += f"**Channel:** {channel_name}\n"
        body += f"**Created by:** {username}\n"
        body += f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        body += f"**Title:** {title}"
        
        forgejo = ForgejoAPI(FORGEJO_URL, FORGEJO_TOKEN)
        issue = forgejo.create_issue(owner, repo, title, body)
        
        if issue:
            logger.info(f"Created issue #{issue['number']}: {title}")
            return jsonify({
                'status': 'success',
                'issue_number': issue['number'],
                'issue_url': issue['html_url']
            })
        else:
            return jsonify({'error': 'Failed to create issue'}), 500
            
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health', methods=['GET'])
def health():
    """ヘルスチェックエンドポイント"""
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'forgejo_url': FORGEJO_URL.replace('//', '//***:***@') if FORGEJO_TOKEN else FORGEJO_URL
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
        'data': request.get_data().decode('utf-8', errors='ignore')
    }
    
    logger.info(f"Debug info: {debug_info}")
    
    return jsonify({
        'message': 'Debug endpoint response',
        'received_data': debug_info,
        'server_config': {
            'forgejo_url': FORGEJO_URL,
            'has_forgejo_token': bool(FORGEJO_TOKEN),
            'has_mattermost_token': bool(MATTERMOST_TOKEN)
        }
    })

if __name__ == '__main__':
    if not FORGEJO_TOKEN:
        logger.error("FORGEJO_TOKEN environment variable is required")
        exit(1)
    
    if not MATTERMOST_TOKEN:
        logger.warning("MATTERMOST_TOKEN not set - token verification disabled")
    
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting server on port {port}")
    logger.info(f"Forgejo URL: {FORGEJO_URL}")
    logger.info(f"Debug mode: {debug}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
