# Mattermost-Forgejo Enhanced Bridge Docker Setup

This directory contains a Docker Compose setup for running the Mattermost-Forgejo Enhanced Bridge with Mattermost service. **This setup assumes you already have a Forgejo instance running.**

## Services Included

- **Bridge Service**: The enhanced bridge application (Python/Flask)
- **Mattermost**: Team communication platform
- **PostgreSQL**: Database for Mattermost

## Prerequisites

- **Forgejo instance**: Must be running and accessible (default: http://localhost:3000)
- Docker and Docker Compose installed

## Quick Start

1. **Clone and navigate to the directory**:
   ```bash
   cd example/enhanced_bridge
   ```

2. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your actual configuration values
   ```

3. **Start all services**:
   ```bash
   docker-compose up -d
   ```

4. **Access the services**:
   - Forgejo: http://localhost:3000 (External - already running)
   - Mattermost: http://localhost:8065
   - Bridge API: http://localhost:5005

## Configuration Steps

### 1. Initial Setup

After starting the services, complete the initial setup:

1. **Configure Forgejo OAuth2** (http://localhost:3000):
   - Go to your existing Forgejo instance
   - Configure OAuth2 application (see section below)

2. **Setup Mattermost** (http://localhost:8065):
   - Complete the initial setup
   - Create team and channels
   - Configure integrations

### 2. OAuth2 Configuration (Forgejo)

1. Go to Forgejo Settings � Applications � OAuth2 Applications
2. Create new OAuth2 application:
   - **Application Name**: Mattermost Bridge
   - **Redirect URI**: `http://localhost:5005/auth/callback`
   - **Scopes**: `read:user,read:repository,write:repository,write:issue`
3. Copy the Client ID and Client Secret to your `.env` file

### 3. Mattermost Integration Setup

1. **Create Slash Command**:
   - Go to Integrations � Slash Commands
   - Create new command:
     - **Command**: `/issue`
     - **Request URL**: `http://bridge:5005/webhook`
     - **Method**: `POST`
   - Copy the token to your `.env` file

2. **Create Bot Account** (Optional):
   - Go to Integrations � Bot Accounts
   - Create new bot for API access
   - Copy the token to your `.env` file

### 4. Webhook Configuration

1. **Forgejo Webhook**:
   - Go to repository settings � Webhooks
   - Add webhook:
     - **Payload URL**: `http://bridge:5005/webhook`
     - **Content Type**: `application/json`
     - **Secret**: Use the same value as `WEBHOOK_SECRET` in `.env`
     - **Events**: Issues, Issue Comments, Pull Requests

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Required Configuration
FORGEJO_CLIENT_ID=your_forgejo_oauth_client_id
FORGEJO_CLIENT_SECRET=your_forgejo_oauth_client_secret
WEBHOOK_SECRET=your_webhook_secret_here
MATTERMOST_TOKEN=your_mattermost_slash_command_token
MATTERMOST_API_TOKEN=your_mattermost_api_token
FLASK_SECRET_KEY=your_flask_secret_key_here

# Optional Configuration (defaults shown)
FORGEJO_URL=http://forgejo:3000
MATTERMOST_API_URL=http://mattermost:8065
BASE_URL=http://localhost:5005
DEBUG=false
```

## Usage

### Authentication

Users must authenticate with Forgejo before creating issues:

```bash
/issue auth
```

### Creating Issues

```bash
/issue <owner> <repo> <title>

Optional detailed description
on multiple lines...
```

### Status Check

```bash
/issue status
```

## API Endpoints

- `GET /` - Service information
- `GET /health` - Health check
- `GET /debug` - Debug information
- `GET /auth/connect` - OAuth2 authentication start
- `GET /auth/callback` - OAuth2 callback
- `POST /webhook` - Webhook endpoint for both Mattermost and Forgejo

## Data Persistence

The following volumes are created for data persistence:

- `forgejo-data`: Forgejo repositories and configuration
- `postgres-data`: PostgreSQL database
- `mattermost-data`: Mattermost files and uploads
- `mattermost-logs`: Mattermost log files
- `mattermost-config`: Mattermost configuration
- `mattermost-plugins`: Mattermost plugins
- `./data`: Bridge application database (SQLite)

## Troubleshooting

### Common Issues

1. **OAuth2 Authentication Fails**:
   - Check redirect URI configuration
   - Verify client ID and secret
   - Ensure services can communicate

2. **Webhook Not Receiving Events**:
   - Check webhook secret configuration
   - Verify network connectivity between services
   - Review webhook payload URL

3. **Database Connection Issues**:
   - Wait for PostgreSQL to fully start
   - Check database credentials
   - Verify network connectivity

### Logs

View logs for each service:

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f bridge
docker-compose logs -f forgejo
docker-compose logs -f mattermost
```

### Reset Everything

To completely reset the setup:

```bash
docker-compose down -v
docker-compose up -d
```

## Development

For development mode:

1. Set `DEBUG=true` in `.env`
2. The bridge application will auto-reload on code changes
3. Access debug endpoint: http://localhost:5005/debug

## Security Notes

- Change default passwords in production
- Use strong secrets for OAuth2 and webhooks
- Configure proper firewall rules
- Use HTTPS in production environments
- Regularly update container images

## Support

For issues and support:
- Check the logs using `docker-compose logs`
- Review the API debug endpoint at `/debug`
- Verify network connectivity between services