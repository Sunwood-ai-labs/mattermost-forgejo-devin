<div align="center">

# mattermost-forgejo-devin

![](https://github.com/user-attachments/assets/7a1369a3-b49b-45ac-8833-6e90b3efa2f9)

<p>
  <img src="https://img.shields.io/badge/Python-3.8+-blue?logo=python" />
  <img src="https://img.shields.io/badge/Flask-2.3+-green?logo=flask" />
  <img src="https://img.shields.io/badge/Mattermost-Chat-blue?logo=mattermost" />
  <img src="https://img.shields.io/badge/Forgejo-Git-orange?logo=git" />
</p>

**Self-hosted AI dev assistant with Mattermost & Forgejo integration**

MattermostとForgejoを連携させるPythonブリッジサーバー - オープンソース版Devinを目指したセルフホスト開発支援ツール

</div>

## 🎯 概要

Mattermostのチャットから直接Forgejoのイシューを作成できるブリッジサーバーです。チーム開発でのコミュニケーションとタスク管理を seamless に連携させ、開発ワークフローを劇的に改善します。

### ✨ 主な機能

- 🗣️ **スラッシュコマンド**: `/issue owner repo "title"` でイシュー作成
- 🔒 **セキュア認証**: トークンベースの認証システム
- 📝 **リッチコンテンツ**: Mattermost情報を含む詳細なイシュー本文
- 🌐 **RESTful API**: ヘルスチェックやデバッグエンドポイント
- 🔄 **リアルタイム処理**: 即座にイシューを作成してフィードバック

## 🚀 クイックスタート

### 必要要件

- Python 3.8以上
- [uv](https://docs.astral.sh/uv/) パッケージマネージャー
- 動作中のMattermostサーバー
- 動作中のForgejoサーバー

### インストール

```bash
# リポジトリをクローン
git clone <repository-url>
cd mattermost-forgejo-devin

# 依存関係をインストール
uv sync

# 環境変数を設定
cp .env.example .env
```

### 環境設定

`.env`ファイルを編集：

```bash
# Forgejo設定
FORGEJO_URL=http://192.168.0.131:3000
FORGEJO_TOKEN=your_forgejo_personal_access_token

# Mattermost設定
MATTERMOST_TOKEN=your_mattermost_slash_command_token
WEBHOOK_SECRET=your_webhook_secret

# サーバー設定
PORT=5000
DEBUG=false
```

### サーバー起動

```bash
uv run python mattermost_forgejo_bridge.py
```

## ⚙️ セットアップガイド

### 1. Forgejoでトークン作成

1. Forgejo管理画面 → Settings → Applications → Personal Access Tokens
2. 新しいトークンを作成（`repo`権限必要）
3. 生成されたトークンを `.env` の `FORGEJO_TOKEN` に設定

### 2. Mattermostでスラッシュコマンド設定

1. 管理画面 → Integrations → Slash Commands → Add Slash Command
2. 設定値：
   - **タイトル**: `Forgejo Issue Creator`
   - **説明**: `Create Forgejo issues from Mattermost`
   - **コマンドトリガーワード**: `issue`
   - **リクエストURL**: `http://YOUR_SERVER_IP:5000/webhook`
   - **リクエストメソッド**: `POST`
   - **Response Username**: `Forgejo Bot`
3. 生成されたトークンを `.env` の `MATTERMOST_TOKEN` に設定

### 3. サービス起動確認

```bash
# ヘルスチェック
curl http://localhost:5000/health

# デバッグ情報確認
curl http://localhost:5000/debug
```

## 💬 使用方法

### 基本的なコマンド

```bash
# 基本構文
/issue <owner> <repo> <title>

# 実例
/issue myorg webapp "ログイン機能のバグ修正"
/issue teamname backend "API レスポンス時間の改善"
/issue john-doe personal-site "ダークモード対応"
```

### レスポンス例

**成功時:**
```
✅ Issue Created Successfully!

Title: ログイン機能のバグ修正
Repository: myorg/webapp
Issue #42: http://forgejo.example.com/myorg/webapp/issues/42
```

**エラー時:**
```
❌ Failed to create issue

Possible causes:
- Invalid repository owner/name
- Insufficient permissions
- Forgejo server connection issues
```

## 🔧 API エンドポイント

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/` | GET/POST | ルートエンドポイント（接続テスト） |
| `/webhook` | POST | Mattermostからのスラッシュコマンド処理 |
| `/health` | GET | ヘルスチェック |
| `/debug` | GET/POST | デバッグ情報表示 |

### ヘルスチェック例

```bash
curl http://localhost:5000/health
```

```json
{
  "status": "healthy",
  "timestamp": "2025-07-08T07:03:32.123456",
  "version": "1.0.0",
  "forgejo_url": "http://192.168.0.131:3000"
}
```

## 📋 作成されるイシューの内容

```markdown
## Issue created from Mattermost

**Channel:** general
**Team:** development
**Created by:** @alice
**Date:** 2025-07-08 07:03:32 UTC

**Original Request:** `myorg webapp "ログイン機能のバグ修正"`

---

**Description:**
ログイン機能のバグ修正
```

## 🛠️ 開発・カスタマイズ

### デバッグモード

```bash
DEBUG=true uv run python mattermost_forgejo_bridge.py
```

### ログ確認

```bash
# リアルタイムログ監視
tail -f /var/log/mattermost-forgejo-devin/app.log
```

### カスタマイズポイント

- **イシュー本文テンプレート**: `handle_slash_command()` 関数内
- **認証方式**: `verify_token()` 関数
- **エラーハンドリング**: 各エンドポイント内

## 🚨 トラブルシューティング

### よくある問題

| 問題 | 原因 | 解決方法 |
|------|------|----------|
| 認証エラー | 無効なトークン | `.env` のトークン設定確認 |
| リポジトリアクセスエラー | 権限不足 | Forgejoでリポジトリアクセス権限確認 |
| 接続エラー | サーバー未起動 | Forgejo/Mattermostサーバー状態確認 |
| コマンド無応答 | Webhook URL間違い | Mattermost設定のURL確認 |

### デバッグコマンド

```bash
# 設定確認
curl -X POST http://localhost:5000/debug

# 接続テスト
curl http://localhost:5000/

# Forgejo API テスト
curl -H "Authorization: token YOUR_TOKEN" \
     http://forgejo.example.com/api/v1/user
```


## 🤝 貢献

プルリクエストやイシューの報告を歓迎します！

### 開発の流れ

1. このリポジトリをフォーク
2. フィーチャーブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを作成

## 📄 ライセンス

MIT License

## 🙏 謝辞

- [Mattermost](https://mattermost.com/) - オープンソースチャットプラットフォーム
- [Forgejo](https://forgejo.org/) - セルフホスト可能なGitサービス
- [Devin](https://devin.ai/) - AI開発アシスタントのインスピレーション

---

**🌟 スターを付けていただけると開発の励みになります！**
