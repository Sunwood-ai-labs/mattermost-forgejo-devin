# example/ ディレクトリ構成・利用ガイド

この example/ ディレクトリには、Mattermost-Forgejo連携の各種ブリッジ実装が用途別にまとめられています。  
**用途や要件に応じて、必要なブリッジのディレクトリを選択してご利用ください。**

---

## ディレクトリ一覧

- `bidirectional_bridge/`  
  シンプルな双方向ブリッジ。MattermostとForgejoの基本的な連携に。

- `enhanced_bridge/`  
  OAuth2認証・高度な機能付きの拡張ブリッジ。ユーザーごとのForgejo認証が必要な場合に。

- `issue_creator/`  
  最小構成のイシュー作成専用ブリッジ。シンプルな用途向け。

- `oauth_bridge/`  
  OAuth2認証対応の標準的なブリッジ。ユーザー認証が必要な場合に。

---

## 使い方（共通）

1. **利用したいブリッジのディレクトリに移動**
2. `.env.example` をコピーして `.env` を作成
3. `.env` をエディタで編集（必要な値をセット）
4. 下記のように実行

```bash
uv run python example/<bridge_dir>/<bridge_main>.py
```

例（Enhanced Bridgeの場合）:
```bash
cd example/enhanced_bridge
cp .env.example .env
# .env を編集
uv run python example/enhanced_bridge/mattermost_forgejo_enhanced_bridge.py
```

---

## 各ブリッジの .env/.env.example について

- 各ディレクトリの `.env.example` には、そのブリッジで必要な環境変数のみが記載されています。
- **不要な変数は省略されているため、必ず example/xxx_bridge/.env.example を確認してください。**
- `.env` は `.env.example` をコピーして編集してください。

---

## 参考

- それぞれのブリッジの詳細な仕様やAPIは、ルートの [`README.md`](../README.md:1) も参照してください。
- 不明点やトラブルは、各ブリッジの .env.example のコメントやルートREADMEの「トラブルシューティング」もご覧ください。
