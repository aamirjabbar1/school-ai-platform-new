# School AI Platform

A complete AI-powered educational platform for schools with student, teacher, and admin dashboards. The AI chatbot is strictly limited to school curriculum content using Retrieval-Augmented Generation (RAG).

---

## Features

| Role | Capabilities |
|------|-------------|
| **Student** | AI chatbot (curriculum-only), view/submit assignments, AI-assisted answers, chat history |
| **Teacher** | AI teaching assistant, create assignments, generate exam papers with AI, grade submissions |
| **Admin** | User management, knowledge base management, upload books/materials, system dashboard |

### AI Chatbot (RAG System)
- Answers ONLY from uploaded school books and curriculum materials
- Uses PostgreSQL full-text search to find relevant content chunks
- Streams responses in real-time
- Supports English and Urdu
- Cites source documents in responses

---

## Tech Stack

- **Frontend:** React 18, Vite, Tailwind CSS, React Router v6
- **Backend:** Node.js, Express.js
- **Database:** PostgreSQL with Sequelize ORM
- **AI:** Anthropic Claude API (`claude-opus-4-6`) with RAG
- **Document Processing:** pdf-parse (PDF), mammoth (DOCX)
- **Deployment:** Docker, Docker Compose, Nginx

---

## Quick Start (Local Development)

### Prerequisites
- Node.js 18+
- PostgreSQL 14+
- Anthropic API Key ([Get it here](https://console.anthropic.com))

### 1. Clone & Install Dependencies

```bash
# Install backend dependencies
cd backend
npm install

# Install frontend dependencies
cd ../frontend
npm install
```

### 2. Configure Environment

```bash
# Backend - edit the .env file
cd backend
# Set your ANTHROPIC_API_KEY and DB credentials in .env
```

### 3. Create PostgreSQL Database

```sql
CREATE DATABASE school_ai_db;
```

### 4. Start the Application

```bash
# Terminal 1 - Start backend
cd backend
npm run dev

# Terminal 2 - Start frontend
cd frontend
npm run dev
```

Open **http://localhost:3000**

### Default Login

| Role | ID | Password |
|------|----|----------|
| Admin | admin001 | admin123 |

> ⚠️ **CHANGE the default admin password immediately after first login!**

---

## Cloud Deployment (Docker)

### 1. Prerequisites
- Docker & Docker Compose installed on your server
- A domain name (optional but recommended)
- Anthropic API Key

### 2. Configure Production Environment

```bash
# Create production .env at project root
cat > .env << EOF
ANTHROPIC_API_KEY=sk-ant-your-key-here
DB_PASSWORD=your_secure_db_password_here
JWT_SECRET=your_super_secure_jwt_secret_min_32_chars
SCHOOL_NAME=Your School Name
EOF
```

### 3. Deploy with Docker Compose

```bash
docker-compose up -d --build
```

Access at **http://your-server-ip**

### AWS EC2 Deployment

```bash
# 1. Launch EC2 instance (Ubuntu 22.04, t3.medium recommended)
# 2. Install Docker
sudo apt update && sudo apt install docker.io docker-compose -y
sudo systemctl start docker

# 3. Clone your project and deploy
git clone <your-repo>
cd school-ai-platform
docker-compose up -d --build
```

### Google Cloud Run / App Engine
- Use the `Dockerfile` in both `backend/` and `frontend/` directories
- Set all environment variables in Cloud Run settings
- Connect to Cloud SQL (PostgreSQL) for the database

---

## Setting Up the Knowledge Base

1. **Log in as Admin** (admin001 / admin123)
2. Go to **Knowledge Base** in the sidebar
3. Click **Upload Book / Material**
4. Fill in: Title, Subject, Class Level
5. Upload the PDF, DOCX, or TXT file
6. The system automatically processes and indexes the content
7. The AI chatbot will now answer questions based on this content

> **Tip:** Upload all textbooks class-by-class and subject-by-subject. The AI will only answer from content that has been uploaded.

---

## Adding Users

### Single User
1. Admin → Manage Users → Add User
2. Fill in Name, Login ID, Password, Role, Class

### Bulk User Creation (API)
```bash
curl -X POST http://localhost:5000/api/admin/users/bulk \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "users": [
      {"name": "Ahmed Ali", "login_id": "STU001", "password": "pass123", "role": "student", "class_name": "Class 8"},
      {"name": "Sara Khan", "login_id": "STU002", "password": "pass123", "role": "student", "class_name": "Class 8"}
    ]
  }'
```

---

## Project Structure

```
school-ai-platform/
├── backend/
│   ├── src/
│   │   ├── config/database.js      # PostgreSQL + full-text search setup
│   │   ├── models/index.js         # All database models + associations
│   │   ├── services/
│   │   │   ├── aiService.js        # Claude API + RAG implementation
│   │   │   └── documentService.js  # PDF/DOCX ingestion + chunking
│   │   ├── controllers/            # Request handlers
│   │   └── routes/index.js         # All API routes
│   └── uploads/                    # Uploaded files (books, submissions)
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── student/            # Student dashboard, chat, assignments
│       │   ├── teacher/            # Teacher dashboard, assignment creation, papers
│       │   └── admin/              # Admin dashboard, users, knowledge base
│       ├── components/
│       │   ├── Layout.jsx          # Sidebar + top bar
│       │   └── ChatInterface.jsx   # Streaming AI chat component
│       └── services/api.js         # API client
├── nginx/nginx.conf                # Reverse proxy configuration
└── docker-compose.yml              # Full-stack deployment
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/chat/message` | AI chat (SSE streaming) |
| GET | `/api/assignments` | Get assignments |
| POST | `/api/assignments` | Create assignment |
| POST | `/api/assignments/ai-generate` | AI-generate assignment content |
| POST | `/api/question-papers/generate` | AI-generate exam paper |
| POST | `/api/documents/upload` | Upload book to knowledge base |
| GET | `/api/admin/users` | Manage users |

---

## Security Features

- JWT authentication with role-based access control (RBAC)
- Passwords hashed with bcrypt (12 rounds)
- Helmet.js security headers
- Rate limiting (100 req/15min per IP)
- File upload validation (type + size)
- AI responses strictly limited to uploaded content

---

## Scaling Recommendations

For large schools (1000+ users):
- **Database:** Use managed PostgreSQL (AWS RDS, Google Cloud SQL)
- **File Storage:** Move uploads to AWS S3 or Google Cloud Storage
- **Vector Search:** Upgrade to pgvector extension or Pinecone for better RAG
- **Load Balancing:** Multiple backend instances behind Nginx
- **Cache:** Add Redis for session caching and rate limiting

---

## Support

For issues or questions, check the documentation or create a support ticket.

**Default Admin Login:** `admin001` / `admin123`
