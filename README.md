# CorpOD IAM Orchestrator

Identity and Access Management automation platform with RAG-powered chatbots, VPN management, and comprehensive user lifecycle handling.

## Architecture

```
IAM_Automation/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/         # REST API routes
│   │   ├── core/        # Config, security, database
│   │   ├── models/      # Pydantic models
│   │   ├── rag/         # RAG engine for chatbots
│   │   └── services/    # Business logic (email, OTP, chatbots)
│   ├── msmtprc          # Email configuration
│   └── .env             # Environment variables
├── frontend/            # React + Vite frontend
│   ├── src/
│   │   ├── api/         # API client functions
│   │   ├── components/  # Reusable React components
│   │   ├── contexts/    # React contexts (theme, auth)
│   │   ├── pages/       # Page components
│   │   └── App.jsx      # Main app component
│   ├── .env             # Frontend environment variables
├── vpn/                 # OpenVPN server setup
│   ├── vpn-server/      # Production VPN server
│   └── dev-server/      # Development VPN endpoint
├── mongodb/             # Database seeding scripts
└── docker-compose.yml   # Container orchestration
```

## Features

- **User Management**: Joiner/Mover/Leaver (JML) workflows
- **Authentication**: JWT-based auth with MFA support
- **Policy Management**: IAM policy creation and enforcement
- **VPN Management**: OpenVPN server integration
- **Chatbots**: RAG-powered admin and user chatbots (Groq LLM)
- **Audit Logging**: Comprehensive access and action logging
- **Email Notifications**: OTP and invitation emails via msmtp

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI, Python 3.10+ |
| Database | MongoDB 7 |
| Frontend | React 19, Vite, TailwindCSS |
| LLM | Groq (Llama3, Mixtral) |
| VPN | OpenVPN |
| Email | msmtp |
| Vector DB | In-memory embeddings |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.10+ (for local development)
- Groq API key

### Using Docker (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd IAM_Automation

# Set environment variables
cp .env.example .env
# Edit .env with your GROQ_API_KEY and other settings

# Start all services
docker-compose up -d
```

Services will be available at:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- MongoDB: localhost:27017
- VPN Server: localhost:4000 (API), localhost:1194 (UDP)

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
cp .env.example .env  # Configure your settings
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Configuration

### Frontend Environment (frontend/.env)

```env
VITE_API_URL=http://localhost:8000
```

### Backend Environment (backend/.env)

```env
MONGODB_URI=mongodb://mongodb:27017
DATABASE_NAME=iam_db
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=your_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
VPN_SERVER_URL=http://vpn-server:4000
```

### Email Configuration (backend/msmtprc)

```conf
defaults
auth on
tls on
tls_starttls on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile /tmp/msmtp.log

account default
host smtp.gmail.com
port 587
from your-email@gmail.com
user your-email@gmail.com
password your-app-password
```

**Note**: For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833) instead of your regular password.

## API Endpoints

| Router | Base Path | Description |
|--------|-----------|-------------|
| auth | /auth | Authentication, login, logout |
| users | /users | User management |
| jml | /jml | Joiner/Mover/Leaver workflows |
| policies | /policies | IAM policy management |
| orchestrator | /orchestrator | Cross-service orchestration |
| vpn | /vpn | VPN client management |
| mfa | /mfa | Multi-factor authentication |
| audit | /audit | Audit log queries |
| admin | /admin | Admin chatbot |
| chatbot | /chatbot | User chatbot |

## Project Structure Details

### Backend API Routes (`backend/app/api/`)
- `auth.py` - JWT authentication endpoints
- `users.py` - User CRUD operations
- `jml.py` - Employee lifecycle management
- `policies.py` - IAM policy endpoints
- `orchestrator.py` - Service coordination
- `vpn.py` - VPN configuration management
- `mfa.py` - OTP generation and verification
- `audit.py` - Audit log retrieval
- `admin.py` - Admin chatbot interface
- `chatbot.py` - User chatbot interface

### Frontend Pages (`frontend/src/pages/`)
- `LoginPage.jsx` - User authentication
- `Joiner.jsx` - New employee onboarding
- `AdminJoiner.jsx` - Admin onboarding view
- `VPNDashboard.jsx` - VPN client management
- `VPNCenter.jsx` - VPN configuration center
- `AdminDashboard.jsx` - Admin overview
- `AuditDashboard.jsx` - Audit log viewer
- `ChatInterface.jsx` - User chatbot interface
- `Profile.jsx` - User profile settings

### RAG Chatbots
- Admin chatbot: Policy and identity management assistance
- User chatbot: Personal access and policy queries
- Uses Groq API with LangChain for RAG implementation

## Security Notes

- Change `SECRET_KEY` in production
- Use strong MongoDB passwords
- Enable TLS for msmtp (configured by default)
- Never commit API keys - use environment variables

## License

Proprietary - CorpOD
